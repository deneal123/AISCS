"""Диалект function-calling у GigaChat + зачистка служебных токенов модели.

Всё, что здесь проверяется, найдено ЖИВЫМ перебором провайдера, а не по документации:
GigaChat расходится с OpenAI в четырёх местах, и каждое молча ломает вызов инструмента.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from service.domain.client.providers.function_dialect import (
    PROVIDER_STATE_KEY,
    accumulate_function_call,
    messages_to_legacy,
    normalize_finish_reason,
    tool_choice_to_function_call,
    tools_to_functions,
    uses_legacy_functions,
)
from service.domain.control_tokens import (
    ControlTokenFilter,
    strip_control_tokens,
)
from service.shared.model_catalog import model_supports_tools

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_graph",
            "description": "Поиск по базе знаний",
            "parameters": {"type": "object", "properties": {"question": {"type": "string"}}},
        },
    }
]


###############################################################################
# Гейт: без него GigaChat вообще не пускали к инструментам                     #
###############################################################################


@pytest.mark.asyncio
async def test_gigachat_is_tool_capable() -> None:
    """Проверено живьём: ВСЕ 13 чат-моделей GigaChat вызывают функции."""
    for model in ("GigaChat-2", "GigaChat-2-Max", "GigaChat-2-Pro"):
        assert await model_supports_tools(model) is True, f"{model} отрезан от инструментов"


@pytest.mark.asyncio
async def test_non_chat_gigachat_models_are_not_tool_capable() -> None:
    """Эмбеддинги и классификаторы того же провайдера на chat/completions дают 404."""
    for model in ("GigaEmbeddings-3B-2025-09", "GigaCheckClassification", "EmbeddingsGigaR"):
        assert await model_supports_tools(model) is False, f"{model} — не чат-модель"


###############################################################################
# Запрос: tools → functions                                                   #
###############################################################################


def test_only_gigachat_uses_the_legacy_dialect() -> None:
    assert uses_legacy_functions("gigachat") is True
    assert uses_legacy_functions("GigaChat") is True
    for openai_like in ("openrouter", "openai", "mws", "routerai", None):
        assert uses_legacy_functions(openai_like) is False


def test_tools_unwrap_to_functions() -> None:
    """`tools` GigaChat не отвергает, а МОЛЧА игнорирует — потому и переводим."""
    assert tools_to_functions(TOOLS) == [TOOLS[0]["function"]]


def test_tool_choice_maps_to_function_call() -> None:
    from service.domain.client.protocol.compiler import ProviderToolCompilationError

    assert tool_choice_to_function_call(None) == "auto"
    assert tool_choice_to_function_call("auto") == "auto"
    assert tool_choice_to_function_call("none") == "none"
    # Required нельзя ослаблять до auto.
    with pytest.raises(ProviderToolCompilationError, match="tool_choice"):
        tool_choice_to_function_call("required")
    forced = {"type": "function", "function": {"name": "search_knowledge_graph"}}
    assert tool_choice_to_function_call(forced) == {"name": "search_knowledge_graph"}


###############################################################################
# Сообщения: канон OpenAI → старый формат                                     #
###############################################################################


def _canonical_round() -> list[dict]:
    return [
        {"role": "user", "content": "Что я загружал про Kubernetes?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search_knowledge_graph",
                        "arguments": '{"question": "Kubernetes"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "Найден k8s-runbook.md"},
    ]


def test_arguments_become_a_dict_not_a_json_string() -> None:
    """Канонная для OpenAI JSON-строка даёт у GigaChat 400 «invalid JSON syntax»."""
    out = messages_to_legacy(_canonical_round())
    call = out[1]["function_call"]
    assert isinstance(call["arguments"], dict), "строка вместо словаря → 400 у провайдера"
    assert call["arguments"] == {"question": "Kubernetes"}
    assert "tool_calls" not in out[1]


def test_tool_result_becomes_a_json_object() -> None:
    """Простой текст в теле результата даёт 422 «invalid function result»."""
    out = messages_to_legacy(_canonical_round())
    result = out[2]
    assert result["role"] == "function"
    assert result["name"] == "search_knowledge_graph", "имя восстановлено по tool_call_id"
    assert json.loads(result["content"]) == {"result": "Найден k8s-runbook.md"}


def test_provider_state_round_trips_only_as_gigachat_field() -> None:
    messages = _canonical_round()
    messages[1][PROVIDER_STATE_KEY] = "state-opaque"

    out = messages_to_legacy(messages)

    assert out[1]["functions_state_id"] == "state-opaque"
    assert PROVIDER_STATE_KEY not in out[1]


def test_plain_messages_pass_through_untouched() -> None:
    plain = [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "здравствуйте"},
    ]
    assert messages_to_legacy(plain) == plain


def test_broken_arguments_do_not_crash_the_turn() -> None:
    """Модель может вернуть нечитаемый JSON — это не повод ронять весь запрос."""
    msgs = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "function": {"name": "f", "arguments": "{не-json"}},
            ],
        }
    ]
    with patch("service.domain.client.providers.function_dialect.logger.warning") as warning:
        assert messages_to_legacy(msgs)[0]["function_call"]["arguments"] == {}

    rendered = warning.call_args.args[0] % warning.call_args.args[1:]
    assert "{не-json" not in rendered
    assert "invalid_json" in rendered


###############################################################################
# Ответ: function_call → канон tool_calls                                     #
###############################################################################


def test_finish_reason_is_normalized_to_canon() -> None:
    """Наверх уходит канон: tool-loop не должен знать про диалекты."""
    assert normalize_finish_reason("function_call") == "tool_calls"
    assert normalize_finish_reason("stop") == "stop"
    assert normalize_finish_reason(None) is None


def test_dict_arguments_from_stream_become_canonical_string() -> None:
    """GigaChat отдаёт arguments СЛОВАРЁМ и одним чанком; OpenAI — строкой по кускам."""
    acc: dict[int, dict] = {}
    delta = SimpleNamespace(
        functions_state_id="state-opaque",
        function_call=SimpleNamespace(
            name="search_knowledge_graph", arguments={"question": "Kubernetes"}
        ),
    )
    accumulate_function_call(delta, acc)
    assert acc[0]["name"] == "search_knowledge_graph"
    assert json.loads(acc[0]["arguments"]) == {"question": "Kubernetes"}
    assert acc[0]["id"], "tool-loop адресует результат по id — он обязан быть"
    assert acc[0][PROVIDER_STATE_KEY] == "state-opaque"


def test_provider_state_is_captured_when_it_arrives_in_a_separate_chunk() -> None:
    acc: dict[int, dict] = {}

    accumulate_function_call(
        SimpleNamespace(functions_state_id="state-only", function_call=None), acc
    )

    assert acc[0][PROVIDER_STATE_KEY] == "state-only"


def test_string_arguments_are_still_concatenated() -> None:
    """Если провайдер шлёт строку по кускам — склеиваем, как в каноне."""
    acc: dict[int, dict] = {}
    for name, part in (("f", '{"q":'), (None, ' "k8s"}')):
        accumulate_function_call(
            SimpleNamespace(function_call=SimpleNamespace(name=name, arguments=part)), acc
        )
    assert json.loads(acc[0]["arguments"]) == {"q": "k8s"}


def test_has_tool_history_detects_tool_artifacts() -> None:
    """Даже без `tools` в текущем вызове история с tool-артефактами требует перевода."""
    from service.domain.client.providers.function_dialect import has_tool_history

    assert has_tool_history(_canonical_round()) is True  # есть role=tool + tool_calls
    assert has_tool_history([{"role": "user", "content": "привет"}]) is False
    assert has_tool_history([]) is False
    assert has_tool_history(None) is False


class _FakeSDKResponse:
    """Мини-имитация SDK-ответа: model_dump()/model_validate() как у pydantic."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def model_dump(self) -> dict:
        return self._data

    @classmethod
    def model_validate(cls, data: dict) -> "_FakeSDKResponse":
        return cls(data)


def test_response_to_canonical_translates_function_call() -> None:
    """B8: не-стрим ответ GigaChat (`function_call`) → канон (`tool_calls`)."""
    from service.domain.client.providers.function_dialect import response_to_canonical

    resp = _FakeSDKResponse(
        {
            "choices": [
                {
                    "finish_reason": "function_call",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {
                            "name": "search_knowledge_graph",
                            "arguments": {"question": "Kubernetes"},
                        },
                    },
                }
            ]
        }
    )
    out = response_to_canonical(resp).model_dump()
    choice = out["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    tc = choice["message"]["tool_calls"][0]
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "search_knowledge_graph"
    # arguments приводятся к канонной JSON-СТРОКЕ (у GigaChat они словарём).
    assert json.loads(tc["function"]["arguments"]) == {"question": "Kubernetes"}
    assert "function_call" not in choice["message"]


def test_response_to_canonical_passthrough_without_function_call() -> None:
    """Обычный ответ (без вызова) возвращается КАК ЕСТЬ — без пересборки/накладных."""
    from service.domain.client.providers.function_dialect import response_to_canonical

    resp = _FakeSDKResponse(
        {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}]}
    )
    assert response_to_canonical(resp) is resp  # тот же объект, не пересобран


def test_response_to_canonical_mutates_live_sdk_shaped_response_without_revalidation() -> None:
    """Live GigaChat omits required OpenAI envelope fields; only the message is translated."""
    from types import SimpleNamespace

    from service.domain.client.providers.function_dialect import response_to_canonical

    message = SimpleNamespace(
        function_call=SimpleNamespace(name="submit", arguments={"value": "ok"}),
        functions_state_id="private-state",
        tool_calls=None,
    )
    choice = SimpleNamespace(message=message, finish_reason="function_call")
    response = SimpleNamespace(choices=[choice])
    private: dict[str, str] = {}

    out = response_to_canonical(response, call_id="call-live", private_state_out=private)

    assert out is response
    assert choice.finish_reason == "tool_calls"
    assert message.function_call is None
    assert message.functions_state_id is None
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].id == "call-live"
    assert json.loads(message.tool_calls[0].function.arguments) == {"value": "ok"}
    assert private == {"value": "private-state"}


###############################################################################
# Служебные токены модели не доезжают до пользователя                         #
###############################################################################


def test_control_tokens_are_stripped() -> None:
    dirty = "Ответ<|eom|> продолжение<|assistant|> хвост<|test_begin|>"
    assert strip_control_tokens(dirty) == "Ответ продолжение хвост"


def test_token_split_across_stream_chunks_is_still_caught() -> None:
    """Ради этого фильтр и стейтфулен: токен приходит разорванным между дельтами."""
    flt = ControlTokenFilter()
    out = "".join(flt.feed(chunk) for chunk in ("Ответ<|", "eo", "m|> дальше"))
    assert flt.flush() == ""
    assert out == "Ответ дальше"


def test_real_text_is_never_eaten() -> None:
    """Незакрытый хвост — не токен. Съесть настоящий текст страшнее, чем пропустить `<`."""
    flt = ControlTokenFilter()
    out = "".join(flt.feed(chunk) for chunk in ("if a < b ", "and c <| d"))
    assert out + flt.flush() == "if a < b and c <| d"


def test_html_and_code_survive() -> None:
    flt = ControlTokenFilter()
    code = "<div>1 < 2</div> Vec<T>"
    assert flt.feed(code) + flt.flush() == code
