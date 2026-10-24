"""Ограничения транспорта, не журнал заданий и не полномочия на исполнение."""

from dataclasses import dataclass
from typing import Any


class ProtocolFailure(ValueError):
    def __init__(self, code: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CompiledRequest:
    body: dict[str, Any]
    functions: dict[str, dict]
    structured_tools: bool = False
    structured_response: bool = False
    stream: bool = False
    include_usage: bool = False
    allow_final: bool = False


def checked_tree(value: Any, depth: int = 0) -> None:
    if depth > 24:
        raise ProtocolFailure("schema_limit")
    if isinstance(value, dict):
        if len(value) > 256:
            raise ProtocolFailure("schema_limit")
        for name, child in value.items():
            # Неподдержанный диалект не должен включать сетевой resolver валидатора.
            if name in {"$dynamicRef", "$recursiveRef"}:
                raise ProtocolFailure("unsupported_schema_reference")
            if name in {"$id", "$schema"}:
                continue
            if name == "$ref" and (not isinstance(child, str) or not child.startswith("#")):
                raise ProtocolFailure("external_schema_reference")
            checked_tree(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > 256:
            raise ProtocolFailure("schema_limit")
        for child in value:
            checked_tree(child, depth + 1)
