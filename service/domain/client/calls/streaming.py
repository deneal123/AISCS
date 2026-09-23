"""Потоковый chat/completions: сборка дельт, вызовы инструментов, фейловер до первой дельты.

⚠️ ГЛАВНОЕ ОТЛИЧИЕ ОТ НЕ-СТРИМОВОГО ПУТИ. Переключиться на другого провайдера можно
ТОЛЬКО пока не отдана первая дельта. После неё ошибка пробрасывается: пользователь уже
видит начало ответа, и тихий свич дописал бы к нему продолжение от другой модели.

⚠️ Активного провайдера читаем ЧЕРЕЗ МОДУЛЬ (`active.ACTIVE_PROVIDER`), а не импортом
имени: его меняет `active.rebuild_provider()` при замене ключа в админке. См. докстринг
`active.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from service.domain.client.protocol import (
    GIGACHAT_TOOL_CAPABILITIES,
    OPENAI_TOOL_CAPABILITIES,
    PinSource,
    ProviderRoundState,
    ProviderRunSession,
    classify_provider_failure,
    compile_toolset,
)
from service.domain.control_tokens import ControlTokenFilter
from service.shared.step_timing import count_llm_call

from .. import active
from ..health import provider_error_detail
from ..model_requirements import ModelRequirement
from ..protocol.compiler import ProviderToolCompilationError
from ..providers.function_dialect import (
    accumulate_function_call,
    messages_to_legacy,
    normalize_finish_reason,
    uses_legacy_functions,
)
from ..registry import (
    _pick_chat_capable_model,
    build_provider_order,
    get_provider_module,
    get_spec,
    qualify_model,
)
from ..resilience import circuit_breaker, provider_policy
from .catalog import get_model_catalog, reorder_owner_first
from .retry import retry_params, with_retry
from .stream_candidate import select_stream_candidate

logger = logging.getLogger(__name__)


def _supports_stream_usage(provider_name: str) -> bool:
    """Понимает ли провайдер `stream_options.include_usage` в финальном чанке.

    ⚠️ ДЕНЕЖНЫЙ ВОПРОС, и ответ на него теперь живёт в спеке провайдера, а не отдельным
    множеством здесь. MWS и GigaChat это поле могут не понять и отклонить ВЕСЬ стрим,
    поэтому у них учёт деградирует на оценку. Пока список был локальным, добавить
    провайдера и забыть его сюда вписать значило молча потерять точный учёт.
    """
    spec = get_spec(provider_name)
    return bool(spec and spec.supports_stream_usage)


def _accumulate_tool_calls(delta, acc: dict[int, dict]) -> None:
    """Склеить дельты tool_calls в целые вызовы.

    Провайдер шлёт вызов инструмента по кускам: на первом фрагменте есть `index`,
    `id` и `function.name`, дальше приходят только обрывки `function.arguments`,
    которые надо конкатенировать в валидный JSON.
    """
    for tc in getattr(delta, "tool_calls", None) or []:
        slot = acc.setdefault(
            int(getattr(tc, "index", 0) or 0), {"id": None, "name": None, "arguments": ""}
        )
        if tc_id := getattr(tc, "id", None):
            slot["id"] = tc_id
        fn = getattr(tc, "function", None)
        if fn is None:
            continue
        if name := getattr(fn, "name", None):
            slot["name"] = name
        if args := getattr(fn, "arguments", None):
            slot["arguments"] += args


# Потолок на накопленное рассуждение. Оно бывает в разы длиннее самого ответа (у
# reasoning-моделей это норма), а нужно для панели трейса — не для промпта и не для
# истории. Обрезаем здесь, чтобы вниз по течению не уезжала мегабайтная строка.
_MAX_REASONING_CHARS = 8000


def _absorb_usage(chunk, state: ProviderRoundState, model: str) -> None:
    """Перенести usage финального чанка в боковой канал. Нет usage — ничего не делаем."""
    usage = getattr(chunk, "usage", None)
    if usage is None:
        return
    state.prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    state.completion = int(getattr(usage, "completion_tokens", 0) or 0)
    state.total = int(getattr(usage, "total_tokens", 0) or 0)
    state.model = model
    # ⚠️ ПОДМНОЖЕСТВО `completion_tokens`, а не добавка к нему: счёт и раньше был верным.
    # Достаём ради видимости — сколько из оплаченного ушло в размышления, а не в текст.
    details = getattr(usage, "completion_tokens_details", None)
    if reasoning_tokens := getattr(details, "reasoning_tokens", None):
        state.reasoning_tokens = int(reasoning_tokens)


def _reasoning_delta(delta) -> str:
    """Кусок «рассуждения» из дельты — как его называет конкретный провайдер.

    🔴 Раньше рассуждение НЕ ЧИТАЛОСЬ ВООБЩЕ. Единственное, что доезжало до панели, —
    теги `<think>` из ТЕЛА ответа (их разбирал фронт). Модели, отдающие рассуждение
    отдельным полем — а это все нынешние reasoning-модели через OpenRouter
    (`delta.reasoning`) и DeepSeek-совместимые (`delta.reasoning_content`), — молча
    показывали пустую панель, хотя рассуждали и брали за это деньги.

    Оба имени, а не одно: провайдеры называют одно и то же по-разному, и «поддержим
    популярное» здесь означает «у половины моделей не работает».
    """
    for name in ("reasoning", "reasoning_content"):
        piece = getattr(delta, name, None)
        if isinstance(piece, str) and piece:
            return piece
    return ""


def _build_stream_payload(
    *,
    provider_name: str,
    messages: list[dict],
    model: str,
    temperature: float | None,
    max_tokens: int | None,
    include_usage: bool = False,
    tools: list[dict] | None,
    tool_choice: str | dict | None,
    provider_session: ProviderRunSession | None,
    compiled=None,
) -> tuple[dict, bool]:
    """Compile one provider-specific request without leaking private run state."""
    payload: dict = {"model": model, "messages": messages, "stream": True}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if include_usage:
        payload["stream_options"] = {"include_usage": True}

    legacy = uses_legacy_functions(provider_name)
    spec = get_spec(provider_name)
    capabilities = (
        spec.tool_capabilities
        if spec
        else GIGACHAT_TOOL_CAPABILITIES
        if legacy
        else OPENAI_TOOL_CAPABILITIES
    )
    if legacy:
        private_state = provider_session.private_state(provider_name) if provider_session else None
        payload["messages"] = messages_to_legacy(messages, private_state=private_state)
    if tools:
        payload.update(
            (
                compiled
                or compile_toolset(
                    tools,
                    provider=provider_name,
                    capabilities=capabilities,
                    tool_choice=tool_choice,
                )
            ).request_fields()
        )
    return payload, legacy


@dataclass
class _StreamRoundAccumulator:
    """Run-private streaming state; only bounded canonical fields leave the adapter."""

    legacy: bool
    provider_call_id: str | None
    capture_private_state: bool
    tool_calls: dict[int, dict] = field(default_factory=dict)
    private_state: dict[str, str] = field(default_factory=dict)
    sanitizer: ControlTokenFilter = field(default_factory=ControlTokenFilter)
    reasoning_parts: list[str] = field(default_factory=list)
    reasoning_len: int = 0
    accepted_delta: bool = False

    def consume(self, chunk, *, state: ProviderRoundState, model: str) -> str:
        _absorb_usage(chunk, state, model)
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        choice = choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason:
            self.accepted_delta = True
        if finish_reason:
            state.finish_reason = normalize_finish_reason(finish_reason)
        delta = getattr(choice, "delta", None)
        if delta is None:
            return ""
        self.accepted_delta = True
        _accumulate_tool_calls(delta, self.tool_calls)
        if self.legacy:
            accumulate_function_call(
                delta,
                self.tool_calls,
                call_id=self.provider_call_id,
                private_state_out=self.private_state if self.capture_private_state else None,
            )
        if self.reasoning_len < _MAX_REASONING_CHARS and (piece := _reasoning_delta(delta)):
            self.reasoning_parts.append(piece)
            self.reasoning_len += len(piece)
        content = getattr(delta, "content", None)
        return self.sanitizer.feed(content) if content else ""

    def finalize(self, state: ProviderRoundState) -> None:
        if self.reasoning_parts:
            state.reasoning = "".join(self.reasoning_parts)[:_MAX_REASONING_CHARS]
        if self.tool_calls:
            state.tool_calls = [
                self.tool_calls[index]
                for index in sorted(self.tool_calls)
                if self.tool_calls[index].get("name")
            ]


async def _stream_one_provider(
    client,
    provider_name: str,
    messages: list[dict],
    model: str,
    *,
    temperature: float | None,
    max_tokens: int | None,
    round_state: ProviderRoundState,
    include_usage: bool,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    provider_session: ProviderRunSession | None = None,
    compiled=None,
):
    """Стрим одного провайдера. Открытие стрима — с ретраями (до первого чанка)."""
    payload, legacy = _build_stream_payload(
        provider_name=provider_name,
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        include_usage=include_usage,
        tools=tools,
        tool_choice=tool_choice,
        provider_session=provider_session,
        compiled=compiled,
    )

    round_state.provider = provider_name
    round_state.model = model

    stream = await with_retry(
        lambda: client.chat.completions.create(**payload),
        label=f"stream-open:{provider_name}",
        **retry_params(),
    )
    accumulator = _StreamRoundAccumulator(
        legacy=legacy,
        provider_call_id=(
            provider_session.next_call_id(provider=provider_name)
            if provider_session is not None
            else None
        ),
        capture_private_state=provider_session is not None,
    )
    async for chunk in stream:
        clean = accumulator.consume(chunk, state=round_state, model=model)
        if (
            accumulator.accepted_delta
            and provider_session is not None
            and not provider_session.has_active_round
        ):
            provider_session.accept_round(
                provider=provider_name,
                model=model,
                source=PinSource.STREAM_DELTA,
                call_id=accumulator.provider_call_id,
            )
        if clean:
            yield clean

    if tail := accumulator.sanitizer.flush():
        yield tail
    accumulator.finalize(round_state)
    if provider_session is not None and accumulator.private_state.get("value"):
        provider_session.set_private_state(provider_name, accumulator.private_state["value"])
    if provider_session is not None and accumulator.accepted_delta:
        provider_session.complete_accepted(
            usage=round_state.usage(),
            finish_reason=round_state.finish_reason,
        )


async def stream_provider_completion(
    messages: list[dict],
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    round_state: ProviderRoundState,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    pin_provider: str | None = None,
    provider_session: ProviderRunSession | None = None,
):
    """Стримить контент-дельты ответа с ретраями и фейловером ДО первой дельты.

    Универсальный адаптер: все провайдеры общаются по OpenAI-совместимому
    chat/completions (choices[0].delta.content). Async-генератор строковых дельт.

    Фейловер на следующий провайдер выполняется только если ошибка случилась до
    выдачи первой дельты. После начала стрима ошибка пробрасывается (тихий свич
    провайдера на полпути недопустим — пользователь уже видит часть ответа).

    ``tools`` — OpenAI-совместимые описания инструментов. Собранные вызовы модель
    кладёт в compatibility-проекцию собранные tool calls и finish reason.
    Гейтить по ``model_supports_tools`` ОБЯЗАТЕЛЬНО: провайдеры без поддержки
    отвечают 400 на неизвестное поле.

    ``pin_provider`` — не искать провайдера, а идти строго к указанному. Нужно в
    tool-loop: все раунды одного вызова обязаны попасть к тому же провайдеру, иначе
    второй раунд уедет к тому, кто про этот ``tool_call_id`` ничего не знает.
    """
    state = round_state

    # Один логический вызов на обращение, а не на попытку фейловера (см. chat.py).
    count_llm_call(model)
    requirement = ModelRequirement.from_call(messages=messages, tools=tools)
    strict_provider = pin_provider or (
        provider_session.pinned_provider if provider_session is not None else None
    )
    from service.domain.run_context import current_execution

    execution = current_execution()
    admission = execution.provider_admission if execution is not None else None
    if strict_provider:
        order = [strict_provider]
    else:
        order = (
            list(admission.snapshot.provider_order)
            if admission is not None
            else build_provider_order(active.ACTIVE_PROVIDER)
        )
        # Владелец выбранной модели — первым (точный роутинг без подмены модели).
        _model_index = (
            admission.qualified_catalog(
                requirement,
                pick_model=_pick_chat_capable_model,
            )[1]
            if admission is not None
            else (await get_model_catalog())[1]
        )
        order = reorder_owner_first(order, model, _model_index)
        if admission is None:
            order = await provider_policy.drop_hard_off(order)
            order = circuit_breaker.drop_cooled_down_local(order)
    last_exc: Exception | None = None
    any_client = False

    for name in order:
        module = get_provider_module(name)
        client, use_model, compiled, admission_failure = await select_stream_candidate(
            name,
            module,
            admission=admission,
            requirement=requirement,
            requested_model=model,
            tools=tools,
            tool_choice=tool_choice,
            qualify=qualify_model,
        )
        if admission_failure is not None:
            last_exc = admission_failure
            if strict_provider:
                raise admission_failure
            continue
        if client is None:
            continue
        any_client = True
        if use_model is None:
            continue

        state.reset_attempt(provider=name, model=use_model)

        started = False
        try:
            async for delta in _stream_one_provider(
                client,
                name,
                messages,
                use_model,
                temperature=temperature,
                max_tokens=max_tokens,
                round_state=state,
                include_usage=_supports_stream_usage(name),
                tools=tools,
                tool_choice=tool_choice,
                provider_session=provider_session,
                compiled=compiled,
            ):
                started = True
                yield delta
            await circuit_breaker.clear_down(name)
            return
        except Exception as exc:  # noqa: BLE001
            session_started = bool(
                provider_session is not None and provider_session.pinned_provider == name
            )
            if started or session_started:
                # Часть ответа уже отдана — фейловер недопустим, пробрасываем. Но
                # провайдера, стабильно умирающего на середине, гасим: иначе он остаётся
                # первым на КАЖДЫЙ запрос и обрывает ответ снова и снова. Cooldown 90 с
                # сам снимет метку, если это был разовый блип.
                if circuit_breaker.should_trip(exc):
                    await circuit_breaker.mark_down(
                        name,
                        reason=classify_provider_failure(exc).code.value,
                    )
                raise
            last_exc = exc
            if isinstance(exc, ProviderToolCompilationError):
                state.provider_fallback_reason = exc.reason_code
            if circuit_breaker.should_trip(exc):
                await circuit_breaker.mark_down(
                    name,
                    reason=classify_provider_failure(exc).code.value,
                )
            # Provider SDK exceptions commonly embed response bodies.  Those bodies
            # may echo request fragments, so transport diagnostics stay bounded.
            logger.warning(
                "Stream provider '%s' failed before first delta: %s",
                name,
                provider_error_detail(exc),
            )
            continue

    if last_exc is not None:
        raise last_exc
    if not any_client:
        raise RuntimeError("LLM client is not configured")
