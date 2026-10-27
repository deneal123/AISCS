"""Project validation errors without trusting input, message, context or location."""

from typing import Any, get_args

from pydantic import TypeAdapter
from pydantic_core import ErrorType
from starlette.requests import Request

_KNOWN_CODES = frozenset(get_args(ErrorType))
_ROOTS = frozenset({"body", "query", "path", "header", "cookie"})
_MAX_ERRORS = 50
_MESSAGES = {
    "missing": "Field required",
    "extra_forbidden": "Extra inputs are not permitted",
    "json_invalid": "Invalid JSON document",
    "json_type": "Invalid JSON value",
    "int_parsing": "Input should be a valid integer",
    "int_type": "Input should be a valid integer",
    "float_parsing": "Input should be a valid number",
    "float_type": "Input should be a valid number",
    "bool_parsing": "Input should be a valid boolean",
    "bool_type": "Input should be a valid boolean",
    "string_type": "Input should be a valid string",
    "string_too_short": "Input is shorter than allowed",
    "string_too_long": "Input is longer than allowed",
    "greater_than": "Value is outside the allowed range",
    "greater_than_equal": "Value is outside the allowed range",
    "less_than": "Value is outside the allowed range",
    "less_than_equal": "Value is outside the allowed range",
    "literal_error": "Value is not one of the allowed options",
    "enum": "Value is not one of the allowed options",
}


def _schema_names(schema: Any) -> set[str]:
    """Only declaration-owned JSON Schema properties, never request data."""
    names: set[str] = set()
    stack = [schema]
    for _ in range(512):
        if not stack:
            break
        node = stack.pop()
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                names.update(key for key in properties if type(key) is str and len(key) <= 120)
            stack.extend(value for value in node.values() if isinstance(value, (dict, list)))
        elif isinstance(node, list):
            stack.extend(value for value in node if isinstance(value, (dict, list)))
    return names


def _declared_names(request: Request) -> set[str]:
    """FastAPI route declarations provide aliases and nested model properties.

    Unknown or unsupported annotations fail closed. Work is bounded and is not
    cached globally: a custom route must not pollute another request's names.
    """
    route = request.scope.get("route")
    fields = []
    body_field = getattr(route, "body_field", None)
    if body_field is not None:
        fields.append(body_field)
    dependencies = [getattr(route, "dependant", None)]
    visited: set[int] = set()
    for _ in range(128):
        if not dependencies:
            break
        dependency = dependencies.pop()
        if dependency is None or id(dependency) in visited:
            continue
        visited.add(id(dependency))
        for group in (
            "body_params",
            "query_params",
            "path_params",
            "header_params",
            "cookie_params",
        ):
            fields.extend(getattr(dependency, group, ()))
        dependencies.extend(getattr(dependency, "dependencies", ()))
    names: set[str] = set()
    for field in fields[:128]:
        alias = getattr(field, "alias", None)
        if type(alias) is str and len(alias) <= 120:
            names.add(alias)
        annotation = getattr(getattr(field, "field_info", None), "annotation", None)
        if annotation is not None:
            try:
                names.update(_schema_names(TypeAdapter(annotation).json_schema()))
            except Exception:
                # UploadedFile/forward refs/custom types may not have JSON Schema.
                # No schema, exception or callable representation is diagnostic.
                continue
    return names


def _location(value: Any, names: set[str]) -> str:
    if not isinstance(value, (list, tuple)):
        return "request"
    parts = []
    for index, part in enumerate(value[:16]):
        if type(part) is str and ((index == 0 and part in _ROOTS) or part in names):
            parts.append(part)
        elif type(part) is int and 0 <= part <= 1_000_000:
            parts.append(str(part))
        else:
            parts.append("*")
    return ".".join(parts) or "request"


def validation_feedback(request: Request, errors: list[Any]) -> list[dict[str, str]]:
    names = _declared_names(request)
    feedback = []
    for error in errors[:_MAX_ERRORS]:
        if not isinstance(error, dict):
            error = {}
        code = error.get("type")
        if type(code) is not str or code not in _KNOWN_CODES:
            code = "value_error"
        feedback.append(
            {
                "field": _location(error.get("loc"), names),
                "message": _MESSAGES.get(code, "Invalid value"),
                "type": code,
            }
        )
    if len(errors) > _MAX_ERRORS:
        feedback[-1] = {
            "field": "request",
            "message": "Additional validation errors omitted",
            "type": "value_error",
        }
    return feedback
