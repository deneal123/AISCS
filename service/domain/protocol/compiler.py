"""Проверенный native tools API Qwen/llama.cpp, без исполнения или ретраев."""

import json
import re
from copy import deepcopy

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..model import MODEL_ID
from .contracts import CompiledRequest, ProtocolFailure, checked_tree
from .schema import native_schema
from .transcript import canonical_messages

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")


def functions_from(tools):
    if not isinstance(tools, list) or len(tools) > 64:
        raise ProtocolFailure("tools_invalid")
    result = {}
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ProtocolFailure("tools_invalid")
        function = tool.get("function")
        if not isinstance(function, dict):
            raise ProtocolFailure("tools_invalid")
        name, parameters = function.get("name"), function.get("parameters")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in result:
            raise ProtocolFailure("tools_invalid")
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            raise ProtocolFailure("tool_schema_invalid")
        if not isinstance(function.get("description", ""), str):
            raise ProtocolFailure("tools_invalid")
        checked_tree(parameters)
        parameters = native_schema(parameters)
        try:
            Draft202012Validator.check_schema(parameters)
        except SchemaError:
            raise ProtocolFailure("tool_schema_invalid") from None
        result[name] = deepcopy(function)
        result[name]["parameters"] = parameters
    return result


def response_schema(body):
    form = body.get("response_format") or {}
    if not isinstance(form, dict):
        raise ProtocolFailure("response_schema_invalid")
    if form.get("type") == "json_schema":
        definition = form.get("json_schema")
        schema = definition.get("schema") if isinstance(definition, dict) else None
        if not isinstance(schema, dict):
            raise ProtocolFailure("response_schema_invalid")
        checked_tree(schema)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError:
            raise ProtocolFailure("response_schema_invalid") from None
        return deepcopy(schema), True
    if form.get("type") == "json_object":
        return {"type": "object"}, True
    if form.get("type") not in {None, "text"}:
        raise ProtocolFailure("response_schema_invalid")
    return {"type": "string"}, False


def compile_request(body: dict) -> CompiledRequest:
    if not isinstance(body, dict):
        raise ProtocolFailure("request_invalid")
    if body.get("model") != MODEL_ID:
        raise ProtocolFailure("model_unavailable", 404)
    if body.get("n", 1) != 1:
        raise ProtocolFailure("single_completion_required")
    if type(body.get("max_tokens", 512)) is not int or not 1 <= body.get("max_tokens", 512) <= 4096:
        raise ProtocolFailure("completion_limit")
    functions = functions_from(body.get("tools", []))
    choice = body.get("tool_choice", "auto")
    forced = None
    if isinstance(choice, dict):
        function = choice.get("function")
        forced = function.get("name") if isinstance(function, dict) else None
        if forced not in functions or choice.get("type") != "function":
            raise ProtocolFailure("tool_choice_invalid")
        choice = "required"
    if (
        not isinstance(choice, str)
        or choice not in {"auto", "none", "required"}
        or (choice == "required" and not functions)
    ):
        raise ProtocolFailure("tool_choice_invalid")
    messages = canonical_messages(body.get("messages") or [])
    raw = {
        name: deepcopy(value)
        for name, value in body.items()
        if name
        in {
            "model",
            "temperature",
            "top_p",
            "max_tokens",
            "stop",
            "seed",
            "presence_penalty",
            "frequency_penalty",
            "response_format",
        }
    }
    raw.update(messages=messages, stream=False)
    stream = body.get("stream", False) is True
    options = body.get("stream_options") or {}
    if not isinstance(options, dict):
        raise ProtocolFailure("stream_options_invalid")
    include_usage = options.get("include_usage") is True
    _, structured = response_schema(body)
    eligible = [forced] if forced else list(functions)
    if functions:
        raw["tools"] = [{"type": "function", "function": functions[name]} for name in eligible]
        # llama.cpp b11846 принимает только строковый выбор. Именованный OpenAI
        # вызов задаём как required с единственной разрешённой функцией.
        raw["tool_choice"] = choice
        raw["parallel_tool_calls"] = False
        if choice == "required":
            # Нативный префикс Qwen: required не допускает свободного текста,
            # который маленькая модель иначе повторяет до лимита вместо вызова.
            prefix = "<tool_call>\n"
            if forced:
                # Имя уже задано вызывающей стороной. Аргументы всегда генерирует
                # модель, а готовый native call и его ID возвращает llama.cpp.
                prefix += '{"name": ' + json.dumps(forced) + ', "arguments": '
            raw["messages"].append({"role": "assistant", "content": prefix})
            raw["continue_final_message"] = "content"
            raw["add_generation_prompt"] = False
    return CompiledRequest(
        raw,
        {name: functions[name] for name in eligible} if choice != "none" else {},
        bool(functions),
        structured,
        stream,
        include_usage,
        allow_final=choice != "required",
    )
