from __future__ import annotations

import json
from typing import Any

from service.domain.usage_ledger import UsageLedger
from service.domain.usage_tracking import is_billable


class ReplyAssembler:
    def __init__(self, usage_ledger: UsageLedger | None = None) -> None:
        self.reply_parts: list[str] = []
        # ``error_messages`` stays as a compatibility facade for older tests/callers.
        # Finalization never persists its free text; only the codes captured below.
        self.error_messages: list[str] = []
        self.error_codes: list[str] = []
        self.metadata: dict[str, Any] = {}
        self.structured_output: Any = None
        # Учёт потребления токенов: суммируется по всем LLM-вызовам запроса
        # (каждый эмитит token_usage ровно один раз в своём AGENT_COMPLETE).
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.per_call_usage: list[dict[str, Any]] = []
        self._usage_ledger = usage_ledger

    def consume(
        self, *, event: Any, stream_chunk_type: Any, error_type: Any, structured_output_type: Any
    ) -> None:
        if event.metadata:
            md = event.metadata
            # Артефакты мульти-интента КОПИМ списком (иначе singular-ключи b64_json/
            # pptx_b64 при update затирали бы друг друга → юзер платит за N, получает 1,
            # аудит A4). multi_intent_artifacts НЕ кладём в metadata как есть — extend'им.
            arts = md.get("multi_intent_artifacts")
            if isinstance(arts, list) and arts:
                self.metadata.setdefault("_pending_artifacts", []).extend(arts)
            # token_usage — внутренние данные учёта, наружу (в ответ клиенту) не
            # просачиваются: накапливаем отдельно, в self.metadata не кладём.
            self.metadata.update(
                {k: v for k, v in md.items() if k not in ("token_usage", "multi_intent_artifacts")}
            )
            self._accumulate_usage(md.get("token_usage"), kind=md.get("kind"))
        if event.type == stream_chunk_type and event.data is not None:
            self.reply_parts.append(str(event.data))
        elif event.type == error_type and event.data:
            self.error_messages.append(str(event.data))
            code = str((event.metadata or {}).get("failure_code") or "internal")
            self.error_codes.append(code)
        elif event.type == structured_output_type and event.data is not None:
            self.structured_output = event.data
            self.metadata = {**self.metadata, "structured_output": event.data}

    def add_usage(self, token_usage: Any) -> None:
        """Учесть вызов, сделанный ВНЕ потока событий процессора.

        ⚠️ Нужен потому, что выбор модели (`route_model`) происходит ДО запуска
        процессора: события ему эмитить некуда, а токены он тратит настоящие. Раньше их
        просто теряли — починка аудита A2 доехала до `/route`, но не до `/run`, то есть
        мимо счёта шёл основной трафик.
        """
        self._accumulate_usage(token_usage, kind=(token_usage or {}).get("kind"))

    def _accumulate_usage(self, token_usage: Any, *, kind: str | None = None) -> None:
        if self._usage_ledger is not None:
            # Production runs register provider calls at the invocation boundary.
            # Event replay and compatibility accumulators are projections only and
            # must never create a second billing source.
            self._sync_usage_from_ledger()
            return
        if isinstance(token_usage, dict) and isinstance(token_usage.get("calls"), list):
            # A subagent may perform several provider/model calls.  Consume each receipt
            # separately so per_call_usage remains a billing source rather than a lossy
            # aggregate attributed to the final model.
            seen: set[str] = set()
            for call in token_usage["calls"]:
                if not isinstance(call, dict):
                    continue
                receipt_id = str(call.get("receipt_id") or "")
                if receipt_id and receipt_id in seen:
                    continue
                if receipt_id:
                    seen.add(receipt_id)
                self._accumulate_single_usage(call, kind=call.get("kind") or kind)
            return
        self._accumulate_single_usage(token_usage, kind=kind)

    def _accumulate_single_usage(self, token_usage: Any, *, kind: str | None = None) -> None:
        # Гейт — общий канон домена, а не своя копия условия: это ПОСЛЕДНИЙ фильтр перед
        # `per_call_usage`, то есть перед ценой. Разойдись он с тем, по которому вызов
        # решил эмитить событие, — часть работы исчезала бы между двумя проверками.
        if not is_billable(token_usage):
            return
        prompt = int(token_usage.get("prompt", 0) or 0)
        completion = int(token_usage.get("completion", 0) or 0)
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        # ⚠️ `kind` НЕСЁТ СМЫСЛ ДЛЯ ПОТРЕБИТЕЛЯ, а не для отладки: по нему воркер
        # отличает служебный вызов от ответа и не показывает «замена модели» там, где
        # просто отработала декомпозиция на мета-модели (см. `SERVICE_USAGE_KINDS`).
        # Отсутствие ключа = основной поток ответа, у него маркера нет по построению.
        self.per_call_usage.append(
            {
                "model": token_usage.get("model"),
                "prompt": prompt,
                "completion": completion,
                **(
                    {"provider": str(token_usage["provider"])}
                    if token_usage.get("provider")
                    else {}
                ),
                **({"kind": str(kind)} if kind else {}),
                **({"estimated": True} if token_usage.get("estimated") else {}),
            }
        )

    def _sync_usage_from_ledger(self) -> None:
        if self._usage_ledger is None:
            return
        self.prompt_tokens = self._usage_ledger.prompt_tokens
        self.completion_tokens = self._usage_ledger.completion_tokens
        calls: list[dict[str, Any]] = []
        for receipt in self._usage_ledger.receipts:
            if not receipt.billable:
                continue
            calls.append(
                {
                    "model": receipt.model,
                    "prompt": receipt.prompt,
                    "completion": receipt.completion,
                    **({"provider": receipt.provider} if receipt.provider else {}),
                    **({"kind": receipt.kind} if receipt.kind else {}),
                    **({"estimated": True} if receipt.estimated else {}),
                }
            )
        self.per_call_usage = calls

    def finalize_usage(self) -> None:
        """Project the immutable run ledger into the historical response contract."""

        self._sync_usage_from_ledger()
        if self._usage_ledger is None:
            return
        anomalies = self._usage_ledger.anomaly_counts()
        if anomalies:
            self.metadata["usage_integrity"] = {
                "anomaly_count": sum(anomalies.values()),
                "reason_codes": sorted(anomalies),
            }

    @property
    def total_tokens(self) -> int:
        self._sync_usage_from_ledger()
        return self.prompt_tokens + self.completion_tokens

    def build_reply(self) -> str:
        reply = "".join(self.reply_parts)
        if reply.strip():
            return reply
        if self.structured_output is None:
            return ""
        if isinstance(self.structured_output, str):
            return self.structured_output
        # Структурированный вывод оборачиваем в markdown code-block, иначе фигурные
        # скобки/кавычки портят рендер на фронте (ReactMarkdown).
        return (
            "```json\n" + json.dumps(self.structured_output, ensure_ascii=False, indent=2) + "\n```"
        )
