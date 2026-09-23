"""Strict, non-mutating JSON Schema validation for provider tool contracts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .capabilities import SchemaProfile

_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")
_GIGACHAT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_FORMATS = frozenset(
    {
        "date",
        "date-time",
        "email",
        "hostname",
        "ipv4",
        "ipv6",
        "time",
        "uri",
        "uuid",
    }
)
_TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})
_COMMON_KEYS = frozenset(
    {
        "type",
        "description",
        "title",
        "default",
        "enum",
        "const",
        "nullable",
        "deprecated",
        "examples",
    }
)
_OBJECT_KEYS = frozenset(
    {
        "properties",
        "required",
        "additionalProperties",
        "minProperties",
        "maxProperties",
    }
)
_ARRAY_KEYS = frozenset({"items", "minItems", "maxItems", "uniqueItems"})
_STRING_KEYS = frozenset({"minLength", "maxLength", "pattern", "format"})
_NUMBER_KEYS = frozenset(
    {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
)
_UNSUPPORTED_COMPOSITION = frozenset(
    {
        "$ref",
        "$defs",
        "definitions",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "dependentSchemas",
        "patternProperties",
        "propertyNames",
        "contains",
        "prefixItems",
        "unevaluatedProperties",
    }
)
_DYNAMIC_DESCRIPTION = "External tool parameter."


class SchemaIssueCode(StrEnum):
    INVALID_SCHEMA = "invalid_schema"
    UNSUPPORTED_KEYWORD = "unsupported_keyword"
    INVALID_NAME = "invalid_name"
    MISSING_DESCRIPTION = "missing_description"
    INVALID_TYPE = "invalid_type"
    INVALID_CONSTRAINT = "invalid_constraint"
    INVALID_REQUIRED = "invalid_required"
    INVALID_ENUM = "invalid_enum"
    DEPTH_LIMIT = "depth_limit"
    NODE_LIMIT = "node_limit"


@dataclass(frozen=True, slots=True)
class SchemaIssue:
    code: SchemaIssueCode
    path: tuple[str, ...]


class ProviderSchemaError(RuntimeError):
    """Safe aggregate schema error; schema content is intentionally not retained."""

    reason_code = "tool_schema"

    def __init__(self, issues: list[SchemaIssue] | tuple[SchemaIssue, ...]) -> None:
        self.issues = tuple(issues)
        self.invalid_count = max(1, len(self.issues))
        super().__init__(self.reason_code)


@dataclass(slots=True)
class _Budget:
    nodes_left: int = 512
    max_depth: int = 16

    def consume(self, depth: int, path: tuple[str, ...]) -> None:
        if depth > self.max_depth:
            raise ProviderSchemaError([SchemaIssue(SchemaIssueCode.DEPTH_LIMIT, path)])
        self.nodes_left -= 1
        if self.nodes_left < 0:
            raise ProviderSchemaError([SchemaIssue(SchemaIssueCode.NODE_LIMIT, path)])


def _detach_openai_schema(
    value: Any,
    *,
    path: tuple[str, ...],
    depth: int,
    budget: _Budget,
    ancestors: set[int],
) -> Any:
    """Detach OpenAI schemas while retaining provider-supported composition keywords."""

    budget.consume(depth, path)
    if isinstance(value, dict):
        identity = id(value)
        if identity in ancestors:
            raise _issue(SchemaIssueCode.INVALID_SCHEMA, path)
        ancestors.add(identity)
        try:
            out: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise _issue(SchemaIssueCode.INVALID_SCHEMA, path)
                out[key] = _detach_openai_schema(
                    item,
                    path=(*path, key),
                    depth=depth + 1,
                    budget=budget,
                    ancestors=ancestors,
                )
            return out
        finally:
            ancestors.remove(identity)
    if isinstance(value, list):
        return [
            _detach_openai_schema(
                item,
                path=(*path, str(index)),
                depth=depth + 1,
                budget=budget,
                ancestors=ancestors,
            )
            for index, item in enumerate(value)
        ]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise _issue(SchemaIssueCode.INVALID_SCHEMA, path)


def _issue(code: SchemaIssueCode, path: tuple[str, ...]) -> ProviderSchemaError:
    return ProviderSchemaError([SchemaIssue(code, path)])


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_common(schema: dict[str, Any], path: tuple[str, ...]) -> None:
    if "description" in schema and not isinstance(schema["description"], str):
        raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
    if "title" in schema and not isinstance(schema["title"], str):
        raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
    if "nullable" in schema and not isinstance(schema["nullable"], bool):
        raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
    if "deprecated" in schema and not isinstance(schema["deprecated"], bool):
        raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
    enum = schema.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum:
            raise _issue(SchemaIssueCode.INVALID_ENUM, path)
        if any(isinstance(item, (dict, list)) for item in enum):
            raise _issue(SchemaIssueCode.INVALID_ENUM, path)


def _allowed_keys(schema_type: str, profile: SchemaProfile) -> frozenset[str]:
    allowed = set(_COMMON_KEYS)
    if schema_type == "object":
        allowed.update(_OBJECT_KEYS)
    elif schema_type == "array":
        allowed.update(_ARRAY_KEYS)
    elif schema_type == "string":
        allowed.update(_STRING_KEYS)
    elif schema_type in {"number", "integer"}:
        allowed.update(_NUMBER_KEYS)
    if profile is SchemaProfile.GIGACHAT:
        allowed.discard("const")
        allowed.discard("deprecated")
        allowed.discard("examples")
        allowed.discard("minProperties")
        allowed.discard("maxProperties")
        allowed.discard("multipleOf")
    return frozenset(allowed)


def _copy_object_schema(
    schema: dict[str, Any],
    *,
    profile: SchemaProfile,
    dynamic: bool,
    path: tuple[str, ...],
    depth: int,
    budget: _Budget,
) -> dict[str, Any]:
    raw_properties = schema.get("properties", {})
    if not isinstance(raw_properties, dict):
        raise _issue(SchemaIssueCode.INVALID_SCHEMA, path)
    properties: dict[str, Any] = {}
    for name, child in raw_properties.items():
        if not isinstance(name, str) or not name or not _NAME_PATTERN.fullmatch(name):
            raise _issue(SchemaIssueCode.INVALID_NAME, path)
        properties[name] = _copy_schema(
            child,
            profile=profile,
            dynamic=dynamic,
            property_schema=True,
            path=(*path, name),
            depth=depth + 1,
            budget=budget,
        )
    required = schema.get("required", [])
    if (
        not isinstance(required, list)
        or any(not isinstance(name, str) for name in required)
        or len(set(required)) != len(required)
        or not set(required).issubset(properties)
    ):
        raise _issue(SchemaIssueCode.INVALID_REQUIRED, path)
    additional = schema.get("additionalProperties", False)
    if not isinstance(additional, bool):
        raise _issue(SchemaIssueCode.UNSUPPORTED_KEYWORD, path)
    out = dict(schema)
    out["properties"] = properties
    out["required"] = list(required)
    if "additionalProperties" in schema or profile is SchemaProfile.GIGACHAT:
        out["additionalProperties"] = additional
    for key in ("minProperties", "maxProperties"):
        if key in schema and not _non_negative_int(schema[key]):
            raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
    return out


def _copy_array_schema(
    schema: dict[str, Any],
    *,
    profile: SchemaProfile,
    dynamic: bool,
    path: tuple[str, ...],
    depth: int,
    budget: _Budget,
) -> dict[str, Any]:
    if not isinstance(schema.get("items"), dict):
        raise _issue(SchemaIssueCode.INVALID_SCHEMA, path)
    out = dict(schema)
    out["items"] = _copy_schema(
        schema["items"],
        profile=profile,
        dynamic=dynamic,
        property_schema=True,
        path=(*path, "items"),
        depth=depth + 1,
        budget=budget,
    )
    for key in ("minItems", "maxItems"):
        if key in schema and not _non_negative_int(schema[key]):
            raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
    if "minItems" in schema and "maxItems" in schema and schema["minItems"] > schema["maxItems"]:
        raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
    return out


def _validate_scalar_constraints(
    schema: dict[str, Any], schema_type: str, path: tuple[str, ...]
) -> None:
    if schema_type == "string":
        for key in ("minLength", "maxLength"):
            if key in schema and not _non_negative_int(schema[key]):
                raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
        if (
            "minLength" in schema
            and "maxLength" in schema
            and schema["minLength"] > schema["maxLength"]
        ):
            raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
        if "pattern" in schema:
            if not isinstance(schema["pattern"], str):
                raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
            try:
                re.compile(schema["pattern"])
            except re.error as exc:
                raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path) from exc
        if "format" in schema and schema["format"] not in _FORMATS:
            raise _issue(SchemaIssueCode.UNSUPPORTED_KEYWORD, path)
    if schema_type in {"integer", "number"}:
        for key in _NUMBER_KEYS:
            if key in schema and not _finite_number(schema[key]):
                raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
        if "multipleOf" in schema and schema["multipleOf"] <= 0:
            raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)
        if "minimum" in schema and "maximum" in schema and schema["minimum"] > schema["maximum"]:
            raise _issue(SchemaIssueCode.INVALID_CONSTRAINT, path)


def _copy_schema(
    schema: Any,
    *,
    profile: SchemaProfile,
    dynamic: bool,
    property_schema: bool,
    path: tuple[str, ...],
    depth: int,
    budget: _Budget,
) -> dict[str, Any]:
    budget.consume(depth, path)
    if not isinstance(schema, dict):
        raise _issue(SchemaIssueCode.INVALID_SCHEMA, path)
    if set(schema).intersection(_UNSUPPORTED_COMPOSITION):
        raise _issue(SchemaIssueCode.UNSUPPORTED_KEYWORD, path)
    schema_type = schema.get("type")
    if not isinstance(schema_type, str) or schema_type not in _TYPES:
        raise _issue(SchemaIssueCode.INVALID_TYPE, path)
    if profile is SchemaProfile.GIGACHAT and schema_type == "null":
        raise _issue(SchemaIssueCode.INVALID_TYPE, path)
    unknown = set(schema).difference(_allowed_keys(schema_type, profile))
    if unknown:
        raise _issue(SchemaIssueCode.UNSUPPORTED_KEYWORD, path)
    _validate_common(schema, path)
    out = dict(schema)
    description = out.get("description")
    if property_schema and (not isinstance(description, str) or not description.strip()):
        if dynamic and profile is SchemaProfile.GIGACHAT:
            out["description"] = _DYNAMIC_DESCRIPTION
        elif profile is SchemaProfile.GIGACHAT:
            raise _issue(SchemaIssueCode.MISSING_DESCRIPTION, path)
    if schema_type == "object":
        out = _copy_object_schema(
            out,
            profile=profile,
            dynamic=dynamic,
            path=path,
            depth=depth,
            budget=budget,
        )
    elif schema_type == "array":
        out = _copy_array_schema(
            out,
            profile=profile,
            dynamic=dynamic,
            path=path,
            depth=depth,
            budget=budget,
        )
    else:
        _validate_scalar_constraints(out, schema_type, path)
    return out


def prepare_provider_schema(
    schema: Any,
    *,
    profile: SchemaProfile,
    dynamic: bool = False,
) -> dict[str, Any]:
    """Validate and return a detached schema for a provider.

    Dynamic schemas receive only missing neutral descriptions where the selected provider
    requires them.  Types, constraints, required properties, and additional-property
    behavior are preserved exactly.
    """

    if profile is SchemaProfile.OPENAI:
        if not isinstance(schema, dict):
            raise _issue(SchemaIssueCode.INVALID_SCHEMA, ("parameters",))
        return _detach_openai_schema(
            schema,
            path=("parameters",),
            depth=0,
            budget=_Budget(),
            ancestors=set(),
        )
    return _copy_schema(
        schema,
        profile=profile,
        dynamic=dynamic,
        property_schema=False,
        path=("parameters",),
        depth=0,
        budget=_Budget(),
    )


def validate_function_name(name: Any, profile: SchemaProfile) -> str:
    if not isinstance(name, str):
        raise _issue(SchemaIssueCode.INVALID_NAME, ("name",))
    pattern = _GIGACHAT_NAME_PATTERN if profile is SchemaProfile.GIGACHAT else _NAME_PATTERN
    if not pattern.fullmatch(name):
        raise _issue(SchemaIssueCode.INVALID_NAME, ("name",))
    return name


__all__ = [
    "ProviderSchemaError",
    "SchemaIssue",
    "SchemaIssueCode",
    "prepare_provider_schema",
    "validate_function_name",
]
