"""Диалект function-calling у GigaChat: старый формат OpenAI вместо `tools`.

Проверено ЖИВЬЁМ (не по документации). GigaChat расходится с каноном OpenAI в четырёх
местах, и каждое ломает вызов по-своему:

1. **Запрос** — `functions` + `function_call`, а не `tools` + `tool_choice`.
   Поле `tools` GigaChat не отвергает, а МОЛЧА игнорирует: ошибки нет, вызова нет, а
   модель вслух объясняет, что «у меня нет доступа к инструменту». Потерю невозможно
   заметить ни по логам, ни по кодам ответа — только по тому, что фича не работает.
2. **Ответ** — `delta.function_call` и `finish_reason="function_call"`, а не
   `delta.tool_calls` / `"tool_calls"`.
3. **`arguments` — СЛОВАРЬ**, в обе стороны. Канонная для OpenAI JSON-строка на входе
   даёт 400 «Your request contains invalid JSON syntax».
4. **Результат инструмента — JSON-ОБЪЕКТ**. Обычный текст (канон OpenAI) даёт
   422 «invalid function result … json string».

Трансляция живёт здесь, а не в агенте: `base.py` говорит на ОДНОМ каноническом диалекте
OpenAI и про провайдеров ничего не знает. Иначе диалекты расползлись бы по tool-loop'у.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from service.domain.client.protocol.capabilities import FunctionDialect

logger = logging.getLogger(__name__)


# У старого формата нет id вызова, а tool-loop в base.py адресует результат по
# `tool_call_id`. Синтезируем — на обратной трансляции id всё равно отбрасывается.
SYNTHETIC_CALL_ID = "call_legacy_0"
PROVIDER_STATE_KEY = "_provider_state_id"


def _provider_state(value: Any) -> str:
    """Keep opaque provider state run-scoped and bounded."""
    return value.strip()[:512] if isinstance(value, str) else ""


def uses_legacy_functions(provider_name: str | None) -> bool:
    """Говорит ли провайдер на СТАРОМ диалекте function-calling.

    ⚠️ Ответ берётся из спеки провайдера, а не из локального множества имён. Раньше
    список жил здесь, и провайдер, забытый в нём, получал канонические `tools` — которые
    он молча игнорирует, — а на tool-историю отвечал 422.

    Импорт отложенный: реестр тянет все провайдер-модули, а gigachat обращается сюда.
    """
    from service.domain.client import registry

    spec = registry.get_spec(str(provider_name or "").strip().lower())
    return bool(spec and spec.tool_capabilities.dialect is FunctionDialect.LEGACY_FUNCTIONS)


def tools_to_functions(tools: list[dict] | None) -> list[dict]:
    """`[{"type":"function","function":{...}}]` → `[{...}]`."""
    out: list[dict] = []
    for tool in tools or []:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            out.append(fn)
    return out


def tool_choice_to_function_call(tool_choice: str | dict | None) -> str | dict:
    """`tool_choice` → `function_call`. По умолчанию "auto"."""
    if tool_choice in (None, "auto", "none"):
        return "none" if tool_choice == "none" else "auto"
    if tool_choice == "required":
        # Required нельзя ослаблять до auto. Компилятор должен либо свести его к
        # единственной forced-функции, либо исключить провайдера до pinning.
        from service.domain.client.protocol.compiler import ProviderToolCompilationError

        raise ProviderToolCompilationError("tool_choice")
    if isinstance(tool_choice, dict):
        name = (tool_choice.get("function") or {}).get("name") or tool_choice.get("name")
        if name:
            return {"name": name}
    return "auto"


def _arguments_to_dict(arguments: Any) -> dict:
    """Канонная JSON-строка → словарь (GigaChat строку не принимает: 400)."""
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(str(arguments or "") or "{}")
    except (TypeError, ValueError):
        logger.warning("Не разобрал arguments для legacy-провайдера: invalid_json")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def messages_to_legacy(messages: list[dict], *, private_state: str | None = None) -> list[dict]:
    """Канон OpenAI → старый формат GigaChat.

    * `assistant.tool_calls[]` → `assistant.function_call` (один вызов: больше старый
      формат не умеет — берём первый и предупреждаем);
    * `role="tool"` → `role="function"` с именем функции и JSON-объектом в теле.
    """
    call_names: dict[str, str] = {}
    out: list[dict] = []

    for msg in messages:
        if not isinstance(msg, dict):
            out.append(msg)
            continue

        role = msg.get("role")
        tool_calls = msg.get("tool_calls")

        if role == "assistant" and tool_calls:
            if len(tool_calls) > 1:
                logger.warning(
                    "Старый формат не умеет параллельные вызовы (%d) — берём первый",
                    len(tool_calls),
                )
            first = tool_calls[0] or {}
            fn = first.get("function") or {}
            name = fn.get("name") or ""
            if call_id := first.get("id"):
                call_names[str(call_id)] = name
            legacy_message = {
                "role": "assistant",
                "content": msg.get("content") or "",
                "function_call": {
                    "name": name,
                    "arguments": _arguments_to_dict(fn.get("arguments")),
                },
            }
            state_id = _provider_state(private_state) or _provider_state(
                msg.get(PROVIDER_STATE_KEY)
            )
            if state_id:
                legacy_message["functions_state_id"] = state_id
            out.append(legacy_message)
            continue

        if role == "tool":
            name = call_names.get(str(msg.get("tool_call_id") or ""), "") or msg.get("name") or ""
            out.append(
                {
                    "role": "function",
                    "name": name,
                    # Тело обязано быть JSON-объектом: простой текст → 422.
                    "content": json.dumps({"result": msg.get("content") or ""}, ensure_ascii=False),
                }
            )
            continue

        # Private canonical fields never go to another provider by accident.
        out.append({key: value for key, value in msg.items() if key != PROVIDER_STATE_KEY})

    return out


def accumulate_function_call(
    delta: Any,
    acc: dict[int, dict],
    *,
    call_id: str | None = None,
    private_state_out: dict[str, str] | None = None,
) -> None:
    """Копить `delta.function_call` в ту же структуру, что и `delta.tool_calls`.

    GigaChat отдаёт вызов ОДНИМ чанком и `arguments` — сразу словарём, тогда как OpenAI
    шлёт JSON-строку по кускам. Приводим к канону (строка), чтобы tool-loop остался один
    на всех провайдеров.
    """
    fc = getattr(delta, "function_call", None)
    state_id = _provider_state(getattr(delta, "functions_state_id", None))
    if fc is None and not state_id:
        return
    slot = acc.setdefault(0, {"id": call_id or SYNTHETIC_CALL_ID, "name": None, "arguments": ""})
    if state_id:
        if private_state_out is not None:
            private_state_out["value"] = state_id
        else:
            # Compatibility for callers not yet carrying ProviderRunSession.
            slot[PROVIDER_STATE_KEY] = state_id
    if fc is None:
        return
    if name := getattr(fc, "name", None):
        slot["name"] = name
    args = getattr(fc, "arguments", None)
    if args is None:
        return
    if isinstance(args, dict):
        slot["arguments"] = json.dumps(args, ensure_ascii=False)
    else:
        slot["arguments"] += str(args)


def normalize_finish_reason(finish_reason: str | None) -> str | None:
    """`"function_call"` → `"tool_calls"`: наверх уходит канон, а не диалект."""
    return "tool_calls" if finish_reason == "function_call" else finish_reason


def has_tool_history(messages: list[dict] | None) -> bool:
    """Есть ли в истории tool-артефакты (`role="tool"` / `assistant.tool_calls`).

    Их нельзя слать GigaChat в каноне OpenAI: `role="tool"` с текстом → 422, а
    `assistant.tool_calls` он не понимает. Даже если в ТЕКУЩЕМ вызове `tools` нет,
    но история их несёт — сообщения надо перевести в старый формат.
    """
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "tool" or msg.get("tool_calls"):
            return True
    return False


def _translate_typed_response(
    response: Any,
    *,
    call_id: str | None,
    private_state_out: dict[str, str] | None,
) -> bool:
    """Translate SDK messages in place without revalidating an incomplete envelope."""

    try:
        from openai.types.chat import ChatCompletionMessageFunctionToolCall

        changed = False
        for choice in getattr(response, "choices", None) or []:
            message = getattr(choice, "message", None)
            function_call = getattr(message, "function_call", None) if message is not None else None
            if function_call is None:
                continue
            name = str(getattr(function_call, "name", "") or "")
            arguments = getattr(function_call, "arguments", None)
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments, ensure_ascii=False)
            state_id = _provider_state(getattr(message, "functions_state_id", None))
            if state_id and private_state_out is not None:
                private_state_out["value"] = state_id
            message.tool_calls = [
                ChatCompletionMessageFunctionToolCall(
                    id=call_id or SYNTHETIC_CALL_ID,
                    type="function",
                    function={"name": name, "arguments": str(arguments or "{}")},
                )
            ]
            message.function_call = None
            if hasattr(message, "functions_state_id"):
                message.functions_state_id = None
            choice.finish_reason = "tool_calls"
            changed = True
        return changed
    except Exception:  # noqa: BLE001 - compatibility objects use the mapping path
        return False


def _translated_mapping(
    response: Any,
    *,
    call_id: str | None,
    private_state_out: dict[str, str] | None,
) -> dict[str, Any] | None:
    """Return a translated model dump, or ``None`` when there is nothing to change."""

    try:
        data = response.model_dump()
    except Exception:  # noqa: BLE001 - a non-SDK compatibility object is unchanged
        return None

    changed = False
    for choice in data.get("choices") or []:
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict):
            continue
        function_call = message.get("function_call")
        if not function_call:
            continue
        state_id = _provider_state(message.get("functions_state_id"))
        if state_id:
            if private_state_out is not None:
                private_state_out["value"] = state_id
            message.pop("functions_state_id", None)
        arguments = function_call.get("arguments")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        message["tool_calls"] = [
            {
                "id": call_id or SYNTHETIC_CALL_ID,
                "type": "function",
                "function": {
                    "name": function_call.get("name") or "",
                    "arguments": arguments or "{}",
                },
            }
        ]
        message.pop("function_call", None)
        if choice.get("finish_reason") == "function_call":
            choice["finish_reason"] = "tool_calls"
        changed = True
    return data if changed else None


def response_to_canonical(
    response: Any,
    *,
    call_id: str | None = None,
    private_state_out: dict[str, str] | None = None,
) -> Any:
    """Не-стрим ответ legacy-провайдера → канон OpenAI (`function_call` → `tool_calls`).

    GigaChat в не-стрим ответе кладёт вызов в `message.function_call` и
    `finish_reason="function_call"`. Канонические потребители (в т.ч. OpenAI-шлюз,
    который сериализует `response.model_dump()` наружу для LDR) читают `tool_calls`.
    Если вызова нет — возвращаем ответ КАК ЕСТЬ (без накладных и без риска пересборки).
    """
    # The OpenAI SDK accepts GigaChat's legacy response through ``model_construct``:
    # required top-level OpenAI fields may therefore be ``None``.  Re-validating the
    # complete response after translating only ``function_call`` then fails on those
    # unrelated fields (live GigaChat returns no OpenAI ``id``/``object``).  Translate
    # the typed message in place first; this preserves the already accepted provider
    # envelope and still gives downstream code canonical tool calls.
    if _translate_typed_response(
        response,
        call_id=call_id,
        private_state_out=private_state_out,
    ):
        return response
    data = _translated_mapping(
        response,
        call_id=call_id,
        private_state_out=private_state_out,
    )
    if data is None:
        return response
    try:
        # Пересобираем ТОТ ЖЕ SDK-класс — сохраняем и attr-доступ, и model_dump().
        return type(response).model_validate(data)
    except Exception:  # noqa: BLE001
        logger.warning("provider response normalization failed code=provider_protocol")
        return response
