"""Не-стримовые вызовы провайдеров: chat/completion/embedding + список моделей.

Фейловер здесь ПОЛНЫЙ: перебираем провайдеров по порядку, пока кто-то не ответит.
Отличие от стрима — там переключаться можно только ДО первой дельты, здесь ответа ещё
никто не видел, поэтому свич безопасен на любой стадии.

⚠️ Активного провайдера читаем ЧЕРЕЗ МОДУЛЬ (`active._ACTIVE`, `active.ACTIVE_PROVIDER`),
а не импортом имени: их меняет `active.rebuild_provider()` при замене ключа в админке.
См. докстринг `active.py`.
"""

from __future__ import annotations

import logging

from service.domain.client.protocol import (
    OPENAI_TOOL_CAPABILITIES,
    ProviderFailure,
    ProviderFailureCode,
    ProviderProtocolError,
    ProviderRunSession,
    classify_provider_failure,
    compile_toolset,
)
from service.domain.client.protocol.compiler import ProviderToolCompilationError
from service.shared.step_timing import count_llm_call

from .. import active
from ..health import provider_error_detail
from ..model_requirements import ModelRequirement
from ..provider_operations import ProviderOperation
from ..registry import (
    _pick_chat_capable_model,
    build_provider_order,
    get_provider_module,
    get_spec,
    qualify_model,
)
from ..resilience import circuit_breaker, provider_policy
from .admitted_call import resolve_admitted_call
from .catalog import get_model_catalog, reorder_owner_first
from .retry import retry_params, with_retry

logger = logging.getLogger(__name__)


def _current_execution():
    from service.domain.run_context import current_execution

    return current_execution()


def _extract_model(args: tuple, kwargs: dict) -> str | None:
    if "model" in kwargs:
        return kwargs.get("model")
    if len(args) >= 2:
        return args[1]
    return None


def _extract_messages(args: tuple, kwargs: dict) -> list[dict]:
    value = kwargs.get("messages") if "messages" in kwargs else (args[0] if args else None)
    return list(value) if isinstance(value, list) else []


def _with_model(args: tuple, kwargs: dict, model: str) -> tuple[list, dict]:
    call_args = list(args)
    call_kwargs = dict(kwargs)
    if "model" in call_kwargs or len(call_args) < 2:
        call_kwargs["model"] = model
    else:
        call_args[1] = model
    return call_args, call_kwargs


async def _provider_order(
    *,
    provider: str | None,
    strict_provider: str | None,
    prefer_model: str | None,
    requirement: ModelRequirement,
) -> tuple[list[str], str | None]:
    """Собрать failover-порядок и владельца исходной модели.

    Policy/circuit gates применяются после выбора владельца: так первый доступный
    fallback не получает модель выбывшего провайдера только потому, что стал первым.
    """
    execution = _current_execution()
    admission = execution.provider_admission if execution is not None else None
    order = (
        list(admission.snapshot.provider_order)
        if admission is not None
        else build_provider_order(active.ACTIVE_PROVIDER)
    )
    if strict_provider:
        owner = strict_provider
        order = [strict_provider]
    elif provider:
        owner = provider
        order = [provider] + [name for name in order if name != provider]
    else:
        model_index = (
            admission.qualified_catalog(
                requirement,
                pick_model=_pick_chat_capable_model,
            )[1]
            if admission is not None
            else (await get_model_catalog())[1]
        )
        owner = model_index.get(prefer_model) if prefer_model else None
        order = reorder_owner_first(order, prefer_model, model_index)
    if admission is not None:
        return order, owner
    order = await provider_policy.drop_hard_off(order)
    return circuit_breaker.drop_cooled_down_local(order), owner


def _provider_client(provider_name: str, module):
    execution = _current_execution()
    if execution is not None and execution.provider_admission is not None:
        return execution.provider_admission.snapshot.client_for(provider_name)
    return getattr(module, "OPENAI_CLIENT", None) if module else None


async def _provider_model(
    *,
    provider_name: str,
    preferred: str | None,
    requirement: ModelRequirement,
) -> str | None:
    """Resolve and positively qualify a model for every provider, including the owner."""

    decision = await qualify_model(
        provider_name,
        prefer=preferred,
        requirement=requirement,
    )
    return decision.model


async def _compile_provider_kwargs(
    *,
    provider_name: str,
    model: str | None,
    kwargs: dict,
    compiled=None,
) -> dict:
    """Compile canonical tools after provider/model qualification."""
    prepared = dict(kwargs)
    tools = prepared.get("tools")
    if not tools:
        return prepared
    spec = get_spec(provider_name)
    compiled = compiled or compile_toolset(
        tools,
        provider=provider_name,
        capabilities=spec.tool_capabilities if spec else OPENAI_TOOL_CAPABILITIES,
        tool_choice=prepared.get("tool_choice"),
    )
    prepared.pop("tools", None)
    prepared.pop("tool_choice", None)
    prepared.update(compiled.request_fields())
    return prepared


def _operation(requirement: ModelRequirement) -> ProviderOperation:
    if requirement.tools:
        return ProviderOperation.TOOL_CHAT
    if requirement.vision:
        return ProviderOperation.VISION_INPUT
    return ProviderOperation.CHAT


def _complete_provider_round(
    session: ProviderRunSession | None,
    *,
    provider_name: str,
    model: str,
    result,
) -> None:
    if session is None:
        return
    choices = getattr(result, "choices", None) or []
    finish_reason = getattr(choices[0], "finish_reason", None) if choices else None
    session.complete_round(
        provider=provider_name,
        model=model,
        response=result,
        finish_reason=str(finish_reason) if finish_reason else None,
    )


async def _chat_candidate(
    name: str,
    module,
    *,
    admission,
    requirement: ModelRequirement,
    prefer_model: str | None,
    tools,
    tool_choice,
) -> tuple[object | None, str | None, object | None, Exception | None, str]:
    if admission is not None:
        admitted = resolve_admitted_call(
            admission,
            name,
            operation=_operation(requirement),
            prefer=prefer_model,
            tools=tools,
            tool_choice=tool_choice,
        )
        failure = None if admitted.accepted else admitted.failure
        return (
            admitted.client,
            admitted.model,
            admitted.compiled_tools,
            failure,
            admitted.status.value,
        )
    client = _provider_client(name, module)
    model = await _provider_model(
        provider_name=name,
        preferred=prefer_model,
        requirement=requirement,
    )
    return client, model, None, None, "no_compatible_model"


def _raise_chat_failure(
    last_exc: Exception | None,
    *,
    any_client: bool,
    any_compatible_model: bool,
) -> None:
    if last_exc is not None:
        raise last_exc
    if any_client and not any_compatible_model:
        raise ProviderProtocolError(
            ProviderFailure(
                code=ProviderFailureCode.NO_COMPATIBLE_MODEL,
                retryable=False,
            )
        )
    raise RuntimeError("LLM client is not configured")


async def create_chat_completion(*args, **kwargs):
    """Chat completion через активного провайдера с ретраями и фейловером.

    При явном ``client=`` фейловер отключается (вызов адресован конкретному
    клиенту — поведение как раньше).

    ``provider=`` (keyword) — явный пин провайдера из шлюза по префиксу модели
    ``"<provider>:<model>"``; НЕ передаётся провайдер-модулю (иначе утёк бы в
    OpenAI-payload). Без него — прежнее поведение (роутинг по каталогу).
    """
    provider = kwargs.pop("provider", None)
    pin_provider = kwargs.pop("pin_provider", None)
    provider_session = kwargs.pop("provider_session", None)
    if provider_session is not None and not isinstance(provider_session, ProviderRunSession):
        raise TypeError("provider_session must be ProviderRunSession")
    # ⚠️ Считаем ЛОГИЧЕСКИЙ вызов — один на обращение к фасаду, а не на каждую попытку
    # фейловера. Иначе бюджет вызовов рос бы от деградации провайдеров, а не от нашего
    # кода, и тест «служебных вызовов не больше N» краснел бы по чужой вине.
    count_llm_call(_extract_model(args, kwargs))
    if kwargs.get("client") is not None:
        return await with_retry(
            lambda: active._ACTIVE.create_chat_completion(*args, **kwargs),
            label="chat:explicit",
            **retry_params(),
        )

    prefer_model = _extract_model(args, kwargs)
    requirement = ModelRequirement.from_call(
        messages=_extract_messages(args, kwargs),
        tools=kwargs.get("tools"),
    )
    strict_provider = pin_provider or (
        provider_session.pinned_provider if provider_session else None
    )
    order, owner = await _provider_order(
        provider=provider,
        strict_provider=strict_provider,
        prefer_model=prefer_model,
        requirement=requirement,
    )
    last_exc: Exception | None = None
    any_client = False
    any_compatible_model = False
    execution = _current_execution()
    run_admission = execution.provider_admission if execution is not None else None
    for name in order:
        module = get_provider_module(name)
        client, use_model, compiled, admission_failure, admission_reason = await _chat_candidate(
            name,
            module,
            admission=run_admission,
            requirement=requirement,
            prefer_model=prefer_model,
            tools=kwargs.get("tools"),
            tool_choice=kwargs.get("tool_choice"),
        )
        if client is None:
            continue
        any_client = True
        if admission_failure is not None or not use_model:
            if admission_failure is not None:
                last_exc = admission_failure
            logger.warning(
                "Provider '%s' excluded before pinning: %s",
                name,
                admission_reason,
            )
            if strict_provider:
                raise admission_failure or ProviderProtocolError(
                    ProviderFailure(
                        code=ProviderFailureCode.NO_COMPATIBLE_MODEL,
                        retryable=False,
                        provider=name,
                    )
                )
            continue
        any_compatible_model = True
        if use_model:
            call_args, call_kwargs = _with_model(args, kwargs, use_model)
        else:
            call_args, call_kwargs = list(args), dict(kwargs)
        try:
            call_kwargs = await _compile_provider_kwargs(
                provider_name=name,
                model=use_model,
                kwargs=call_kwargs,
                compiled=compiled,
            )
        except ProviderToolCompilationError as exc:
            last_exc = exc
            if strict_provider:
                raise
            logger.warning("Provider '%s' excluded before pinning: %s", name, exc.reason_code)
            continue
        if provider_session is not None and name == "gigachat":
            call_kwargs["_provider_session"] = provider_session
        call_kwargs["client"] = client
        try:
            result = await with_retry(
                lambda m=module, a=call_args, k=call_kwargs: m.create_chat_completion(*a, **k),
                label=f"chat:{name}",
                **retry_params(),
            )
            await circuit_breaker.clear_down(name)
            _complete_provider_round(
                provider_session,
                provider_name=name,
                model=str(use_model or prefer_model or ""),
                result=result,
            )
            if provider_session is None:
                # Meta/subagent calls intentionally do not pin the answer provider, but
                # their accounting still needs the actual failover provider/model.
                execution = _current_execution()
                if execution is not None:
                    execution.register_response_provider(
                        result,
                        name,
                        str(use_model or prefer_model or ""),
                    )
            return result
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            # Гасим и на 401/403/429 (лимит/квота/авторизация), не только на транспорте:
            # провайдер без денег бесполезен так же, как недоступный по сети.
            if circuit_breaker.should_trip(exc):
                await circuit_breaker.mark_down(
                    name,
                    reason=classify_provider_failure(exc).code.value,
                )
            logger.warning(
                "Provider '%s' chat failed, trying next: %s",
                name,
                provider_error_detail(exc),
            )
            continue
    _raise_chat_failure(
        last_exc,
        any_client=any_client,
        any_compatible_model=any_compatible_model,
    )


async def create_completion(*args, **kwargs):
    """Completion через активного провайдера (ретраи, без фейловера)."""
    return await with_retry(
        lambda: active._ACTIVE.create_completion(*args, **kwargs),
        label="completion",
        **retry_params(),
    )


async def create_embedding(*args, **kwargs):
    """Embedding через активного провайдера (ретраи; фейловер не делаем — нужна точная модель)."""
    return await with_retry(
        lambda: active._ACTIVE.create_embedding(*args, **kwargs),
        label="embedding",
        **retry_params(),
    )


async def list_available_models(*args, **kwargs) -> list[str]:
    """Агрегированный список моделей ВСЕХ сконфигурированных провайдеров (union).

    Раньше возвращались модели только активного провайдера — из-за чего модели
    других (напр. GigaChat) не были видны в пикере. Теперь объединяем каталоги
    всех провайдеров; роутинг сам направит выбранную модель её владельцу.
    При явном ``client=`` — поведение как раньше (только этот клиент).
    """
    if kwargs.get("client") is not None:
        return await active._ACTIVE.list_available_models(*args, **kwargs)

    aggregated, _ = await get_model_catalog()
    return aggregated
