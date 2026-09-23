"""HTTP-движок агента: исполнение на сайдкаре ``agents`` (Фаза 4 плана
flickering-knitting-wirth).

Реализация ``AgentExecutionPort``, которую воркер выбирает при
``AGENTS__ENGINE_MODE=http``. Стримит ``POST /run`` на сайдкар и ВОССТАНАВЛИВАЕТ
``AgentEvent`` из строк NDJSON, отдавая их в тот же колбэк ``on_event``, что и
in-process движок. Благодаря этому воркер НЕ меняется: он как и раньше форвардит
события в Redis-стрим, копит текст ответа, а из терминального result-dict считает
биллинг и персистит артефакты.

Тело запроса — ``AgentRunInput`` (своя копия контракта, см. ``contracts/run.py``):
backend уже собрал
историю/память/резюме сам (Фаза 0b), поэтому сайдкар не ходит в его PG/Redis/MinIO.
Несериализуемое (``pseudo_session``, сам ``on_event``) в тело не попадает — сайдкар
строит сессию из ``history_messages``, а события возвращает потоком.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from service.infrastructure.agents_client.contracts.events import AgentEvent, EventType
from service.infrastructure.agents_client.contracts.protocol_manifest import (
    load_protocol_manifest,
)
from service.infrastructure.agents_client.contracts.run import AgentRunInput

logger = logging.getLogger(__name__)

# Дискриминаторы терминальных строк потока /run (симметрично сайдкару).
RESULT_KEY = "__result__"
ERROR_KEY = "__error__"
_HARD_STOP_GRACE_SEC = 60.0
_TRANSPORT_FLUSH_SEC = 5.0
_DEFAULT_RUN_TIMEOUT_SEC = 570.0
_PROTOCOL = load_protocol_manifest()


@dataclass(slots=True)
class _RunTerminalState:
    """Latch the only result that is allowed to reach accounting.

    ``__error__`` is deliberately not a billable terminal: a sidecar can emit it
    while recovering a deadline and still flush a complete partial result with
    the provider usage.  A valid result therefore wins over diagnostics, but
    only the first valid result is ever accepted.
    """

    result: dict[str, Any] | None = None
    error: str | None = None
    anomaly_count: int = 0
    reasons: set[str] = field(default_factory=set)

    def anomaly(self, reason: str) -> None:
        self.anomaly_count += 1
        bounded = reason if reason in _PROTOCOL.run_integrity_reasons else "invalid_record"
        self.reasons.add(bounded)

    @staticmethod
    def valid_result(value: Any) -> bool:
        if not isinstance(value, dict) or not isinstance(value.get("reply"), str):
            return False
        metadata = value.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            return False
        per_call_usage = value.get("per_call_usage")
        return per_call_usage is None or (
            isinstance(per_call_usage, list)
            and all(isinstance(item, dict) for item in per_call_usage)
        )


def _run_integrity_event(state: _RunTerminalState) -> AgentEvent | None:
    if not state.anomaly_count:
        return None
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        seq=0,
        agent_name="transport",
        data="",
        metadata={
            "kind": "run_integrity",
            "run_integrity": {
                "policy": "first_valid_result",
                "anomaly_count": state.anomaly_count,
                "reasons": sorted(state.reasons),
            },
        },
    )


def _record_invalid_event(state: _RunTerminalState, correlation_id: str) -> None:
    """Drop an untrusted event without reflecting its fields into logs or Redis/WS."""

    state.anomaly("invalid_event")
    logger.warning(
        "agents sidecar protocol anomaly [cid=%s] category=invalid_event",
        correlation_id,
    )


class HttpAgentEngine:
    """``AgentExecutionPort`` поверх HTTP-сайдкара ``agents``."""

    def __init__(self, config: Any) -> None:
        agents_cfg = getattr(config, "agents", None)
        self._base = str(getattr(agents_cfg, "sidecar_url", "") or "").rstrip("/")
        self._timeout = float(getattr(agents_cfg, "sidecar_timeout_sec", 600.0) or 600.0)
        self._run_timeout = float(
            getattr(agents_cfg, "run_timeout_sec", _DEFAULT_RUN_TIMEOUT_SEC)
            or _DEFAULT_RUN_TIMEOUT_SEC
        )
        # ⚠️ Ключ обязателен: сайдкар закрыл `/run`. До этого САМАЯ нагруженная ручка —
        # с полным пользовательским контекстом, историей и биллингом — была открыта для
        # всего, что дотянулось до внутренней сети, тогда как `/tools/web-search` уже
        # требовала ключ. Приоритет был расставлен ровно наоборот.
        self._key = str(getattr(agents_cfg, "llm_gateway_api_key", "") or "")

    def _transport_timeout(self, agent_settings: Any) -> float:
        """Keep the HTTP reader alive through sidecar's own recovery window."""
        configured = self._run_timeout
        if isinstance(agent_settings, dict) and "run_timeout_sec" in agent_settings:
            try:
                configured = float(agent_settings["run_timeout_sec"])
            except (TypeError, ValueError):
                configured = self._run_timeout
        if configured <= 0:
            return self._timeout
        return configured + _HARD_STOP_GRACE_SEC + _TRANSPORT_FLUSH_SEC

    def _headers(self) -> dict[str, str]:
        """Ключ + сквозной идентификатор запроса.

        ⚠️ Корреляция — не украшение лога. Один пользовательский вопрос проходит через
        воркер, сайдкар агентов и дальше через duckdb/graphify; без общего
        идентификатора собрать его историю из трёх наборов логов нельзя вовсе.
        Идентификатор выставляет воркер (`set_correlation_context`), здесь он только
        уезжает на провод.
        """
        from service.shared.observability.context import get_correlation_id

        headers: dict[str, str] = {}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        cid = get_correlation_id()
        if cid:
            # Пустой не шлём: заголовок-прочерк врал бы о наличии трассы.
            headers["X-Correlation-Id"] = cid
        return headers

    async def execute(self, *, on_event: Any = None, **kwargs: Any) -> dict[str, Any]:
        """Прогнать агента на сайдкаре; вернуть result-dict как in-process движок.

        ``on_event`` вызывается по мере прихода событий (стрим не буферизуем) — воркер
        публикует их в Redis сразу, поэтому пользователь видит ответ по мере генерации.
        """
        if not self._base:
            raise RuntimeError("AGENTS__SIDECAR_URL не задан — некуда слать /run")

        # В тело берём ТОЛЬКО поля контракта: pseudo_session/on_event несериализуемы.
        payload = AgentRunInput(
            **{k: v for k, v in kwargs.items() if k in AgentRunInput.model_fields}
        )

        terminal = _RunTerminalState()
        from service.shared.observability.context import get_correlation_id

        correlation_id = get_correlation_id() or "-"

        timeout = self._transport_timeout(payload.agent_settings)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base}/run",
                json=payload.model_dump(mode="json"),
                headers=self._headers(),
            ) as resp:
                if resp.status_code >= 400:
                    # Error bodies are supplied by a remote process and can contain
                    # model text or echoed request data.  Keep them out of logs,
                    # exceptions and stored chat metadata.
                    await resp.aread()
                    logger.warning(
                        "agents sidecar HTTP failure [cid=%s] status=%d",
                        correlation_id,
                        resp.status_code,
                    )
                    raise RuntimeError(f"agents sidecar HTTP {resp.status_code}")

                async for raw in resp.aiter_lines():
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        terminal.anomaly("invalid_json")
                        logger.warning(
                            "agents sidecar: non-JSON line in /run [cid=%s] (chars=%d)",
                            correlation_id,
                            len(line),
                        )
                        continue

                    if not isinstance(data, dict):
                        terminal.anomaly("invalid_record")
                        continue

                    has_result = RESULT_KEY in data
                    has_error = ERROR_KEY in data
                    if has_result and has_error:
                        terminal.anomaly("mixed_terminal")
                        continue
                    if has_result:
                        candidate = data[RESULT_KEY]
                        if not terminal.valid_result(candidate):
                            terminal.anomaly("invalid_result")
                        elif terminal.result is not None:
                            terminal.anomaly("duplicate_result")
                        else:
                            terminal.result = candidate
                            if terminal.error is not None:
                                terminal.anomaly("result_after_error")
                        continue
                    if has_error:
                        value = data[ERROR_KEY]
                        if not isinstance(value, str) or not value.strip():
                            terminal.anomaly("invalid_error")
                        elif terminal.result is not None:
                            terminal.anomaly("error_after_result")
                        else:
                            terminal.error = value
                        continue
                    if terminal.result is not None:
                        terminal.anomaly("event_after_result")
                        continue
                    if on_event is None:
                        continue
                    try:
                        # AgentEvent игнорирует лишние транспортные поля сериализатора
                        # (job_id/message/timestamp/tool_name) — берёт только свои.
                        on_event(AgentEvent(**data))
                    except Exception:
                        _record_invalid_event(terminal, correlation_id)

        if event := _run_integrity_event(terminal):
            if on_event is not None:
                on_event(event)

        # A valid result is the sole billable envelope.  Error diagnostics are
        # meaningful only when the stream never produced one.
        if terminal.error and terminal.result is None:
            logger.warning(
                "agents sidecar /run terminal failure [cid=%s] category=terminal_error",
                correlation_id,
            )
            raise RuntimeError("agents sidecar run failed")
        if terminal.result is None:
            # Молчаливый обрыв опаснее исключения: воркер иначе спишет деньги за пустоту.
            raise RuntimeError("agents sidecar: поток /run кончился без терминального результата")
        return terminal.result
