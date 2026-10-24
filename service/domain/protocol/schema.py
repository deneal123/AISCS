"""Перевод nullable из общего OpenAPI-профиля в нативный JSON Schema."""

from copy import deepcopy

from .contracts import ProtocolFailure

_MAPS = {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
_ARRAYS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_SINGLE = {
    "items",
    "additionalProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
    "contains",
    "not",
    "if",
    "then",
    "else",
    "propertyNames",
}


def native_schema(schema):
    """Меняем только schema nodes: enum/default/examples остаются данными."""
    if not isinstance(schema, dict):
        return deepcopy(schema)
    result = deepcopy(schema)
    nullable = result.pop("nullable", False)
    if type(nullable) is not bool:
        raise ProtocolFailure("tool_schema_invalid")
    kind = result.get("type")
    if nullable and isinstance(kind, str) and kind != "null":
        result["type"] = [kind, "null"]
    elif nullable and isinstance(kind, list) and "null" not in kind:
        result["type"] = [*kind, "null"]
    for key, value in list(result.items()):
        if key in _MAPS and isinstance(value, dict):
            result[key] = {name: native_schema(child) for name, child in value.items()}
        elif key in _ARRAYS and isinstance(value, list):
            result[key] = [native_schema(child) for child in value]
        elif key in _SINGLE:
            result[key] = (
                [native_schema(child) for child in value]
                if key == "items" and isinstance(value, list)
                else native_schema(value)
            )
    return result
