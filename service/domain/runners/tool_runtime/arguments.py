"""Local validation of model-generated tool arguments.

The validator intentionally supports the same conservative schema subset compiled for
providers.  It never invokes user code and never places offending values into errors.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ArgumentIssueCode(StrEnum):
    INVALID_JSON = "invalid_json"
    EXPECTED_OBJECT = "expected_object"
    TYPE_MISMATCH = "type_mismatch"
    REQUIRED = "required"
    ADDITIONAL_PROPERTY = "additional_property"
    ENUM = "enum"
    CONST = "const"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    MULTIPLE_OF = "multiple_of"
    MIN_LENGTH = "min_length"
    MAX_LENGTH = "max_length"
    PATTERN = "pattern"
    MIN_ITEMS = "min_items"
    MAX_ITEMS = "max_items"
    UNIQUE_ITEMS = "unique_items"
    MIN_PROPERTIES = "min_properties"
    MAX_PROPERTIES = "max_properties"
    DEPTH = "depth"
    NODE_LIMIT = "node_limit"
    INVALID_SCHEMA = "invalid_schema"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Bounded error: path identifies schema position, never the rejected value."""

    code: ArgumentIssueCode
    path: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "depth": len(self.path)}


class ToolArgumentError(ValueError):
    reason_code = "invalid_arguments"

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = tuple(issues[:32])
        self.issue_count = len(issues)
        super().__init__(self.reason_code)


@dataclass(slots=True)
class _ValidationBudget:
    remaining: int = 2048
    max_depth: int = 20

    def consume(self, depth: int, path: tuple[str, ...]) -> ValidationIssue | None:
        if depth > self.max_depth:
            return ValidationIssue(ArgumentIssueCode.DEPTH, path)
        self.remaining -= 1
        if self.remaining < 0:
            return ValidationIssue(ArgumentIssueCode.NODE_LIMIT, path)
        return None


def parse_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        raise ToolArgumentError([ValidationIssue(ArgumentIssueCode.INVALID_JSON)])
    try:
        value = json.loads(arguments or "{}")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ToolArgumentError([ValidationIssue(ArgumentIssueCode.INVALID_JSON)]) from exc
    if not isinstance(value, dict):
        raise ToolArgumentError([ValidationIssue(ArgumentIssueCode.EXPECTED_OBJECT)])
    return value


def canonical_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _matches_type(value: Any, expected: str, nullable: bool) -> bool:
    if value is None:
        return nullable or expected == "null"
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _stable_value(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return f"<{type(value).__name__}>"


def _validate_enum(
    value: Any, schema: dict[str, Any], path: tuple[str, ...]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if "enum" in schema and value not in schema["enum"]:
        issues.append(ValidationIssue(ArgumentIssueCode.ENUM, path))
    if "const" in schema and value != schema["const"]:
        issues.append(ValidationIssue(ArgumentIssueCode.CONST, path))
    return issues


def _validate_number(
    value: int | float, schema: dict[str, Any], path: tuple[str, ...]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    number = float(value)
    if not math.isfinite(number):
        return [ValidationIssue(ArgumentIssueCode.TYPE_MISMATCH, path)]
    if "minimum" in schema and number < schema["minimum"]:
        issues.append(ValidationIssue(ArgumentIssueCode.MINIMUM, path))
    if "maximum" in schema and number > schema["maximum"]:
        issues.append(ValidationIssue(ArgumentIssueCode.MAXIMUM, path))
    if "exclusiveMinimum" in schema and number <= schema["exclusiveMinimum"]:
        issues.append(ValidationIssue(ArgumentIssueCode.MINIMUM, path))
    if "exclusiveMaximum" in schema and number >= schema["exclusiveMaximum"]:
        issues.append(ValidationIssue(ArgumentIssueCode.MAXIMUM, path))
    multiple = schema.get("multipleOf")
    if isinstance(multiple, (int, float)) and multiple > 0:
        quotient = number / float(multiple)
        if not math.isclose(quotient, round(quotient), rel_tol=1e-9, abs_tol=1e-9):
            issues.append(ValidationIssue(ArgumentIssueCode.MULTIPLE_OF, path))
    return issues


def _validate_string(
    value: str, schema: dict[str, Any], path: tuple[str, ...]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if "minLength" in schema and len(value) < schema["minLength"]:
        issues.append(ValidationIssue(ArgumentIssueCode.MIN_LENGTH, path))
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        issues.append(ValidationIssue(ArgumentIssueCode.MAX_LENGTH, path))
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            matched = re.search(pattern, value) is not None
        except re.error:
            issues.append(ValidationIssue(ArgumentIssueCode.INVALID_SCHEMA, path))
        else:
            if not matched:
                issues.append(ValidationIssue(ArgumentIssueCode.PATTERN, path))
    return issues


def _validate_array(
    value: list[Any],
    schema: dict[str, Any],
    path: tuple[str, ...],
    depth: int,
    budget: _ValidationBudget,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if "minItems" in schema and len(value) < schema["minItems"]:
        issues.append(ValidationIssue(ArgumentIssueCode.MIN_ITEMS, path))
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        issues.append(ValidationIssue(ArgumentIssueCode.MAX_ITEMS, path))
    if schema.get("uniqueItems"):
        stable = [_stable_value(item) for item in value]
        if len(stable) != len(set(stable)):
            issues.append(ValidationIssue(ArgumentIssueCode.UNIQUE_ITEMS, path))
    item_schema = schema.get("items")
    if not isinstance(item_schema, dict):
        return [*issues, ValidationIssue(ArgumentIssueCode.INVALID_SCHEMA, path)]
    for index, item in enumerate(value):
        issues.extend(_validate_value(item, item_schema, (*path, str(index)), depth + 1, budget))
        if len(issues) >= 32:
            break
    return issues


def _validate_object(
    value: dict[str, Any],
    schema: dict[str, Any],
    path: tuple[str, ...],
    depth: int,
    budget: _ValidationBudget,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        return [ValidationIssue(ArgumentIssueCode.INVALID_SCHEMA, path)]
    for name in required:
        if name not in value:
            issues.append(ValidationIssue(ArgumentIssueCode.REQUIRED, (*path, str(name))))
    additional = schema.get("additionalProperties", False)
    for name, item in value.items():
        child = properties.get(name)
        if child is None:
            if additional is False:
                issues.append(ValidationIssue(ArgumentIssueCode.ADDITIONAL_PROPERTY, (*path, name)))
            elif isinstance(additional, dict):
                issues.extend(_validate_value(item, additional, (*path, name), depth + 1, budget))
            continue
        if not isinstance(child, dict):
            issues.append(ValidationIssue(ArgumentIssueCode.INVALID_SCHEMA, (*path, name)))
            continue
        issues.extend(_validate_value(item, child, (*path, name), depth + 1, budget))
        if len(issues) >= 32:
            break
    if "minProperties" in schema and len(value) < schema["minProperties"]:
        issues.append(ValidationIssue(ArgumentIssueCode.MIN_PROPERTIES, path))
    if "maxProperties" in schema and len(value) > schema["maxProperties"]:
        issues.append(ValidationIssue(ArgumentIssueCode.MAX_PROPERTIES, path))
    return issues


def _validate_value(
    value: Any,
    schema: dict[str, Any],
    path: tuple[str, ...],
    depth: int,
    budget: _ValidationBudget,
) -> list[ValidationIssue]:
    if limit_issue := budget.consume(depth, path):
        return [limit_issue]
    expected = schema.get("type")
    if not isinstance(expected, str):
        return [ValidationIssue(ArgumentIssueCode.INVALID_SCHEMA, path)]
    if not _matches_type(value, expected, bool(schema.get("nullable"))):
        return [ValidationIssue(ArgumentIssueCode.TYPE_MISMATCH, path)]
    if value is None:
        return []
    issues = _validate_enum(value, schema, path)
    if expected == "object":
        issues.extend(_validate_object(value, schema, path, depth, budget))
    elif expected == "array":
        issues.extend(_validate_array(value, schema, path, depth, budget))
    elif expected == "string":
        issues.extend(_validate_string(value, schema, path))
    elif expected in {"number", "integer"}:
        issues.extend(_validate_number(value, schema, path))
    return issues[:32]


def validate_arguments(arguments: dict[str, Any], schema: Any) -> None:
    if not isinstance(schema, dict):
        raise ToolArgumentError([ValidationIssue(ArgumentIssueCode.INVALID_SCHEMA)])
    issues = _validate_value(arguments, schema, (), 0, _ValidationBudget())
    if issues:
        raise ToolArgumentError(issues)


def parse_and_validate_arguments(arguments: Any, schema: Any) -> tuple[dict[str, Any], str]:
    parsed = parse_arguments(arguments)
    validate_arguments(parsed, schema)
    return parsed, canonical_arguments(parsed)


__all__ = [
    "ArgumentIssueCode",
    "ToolArgumentError",
    "ValidationIssue",
    "canonical_arguments",
    "parse_and_validate_arguments",
    "parse_arguments",
    "validate_arguments",
]
