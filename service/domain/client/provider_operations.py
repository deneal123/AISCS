"""Typed admission for every provider-backed model operation."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any

from .model_catalog import ModelCapability, ModelCatalogSource
from .model_requirements import ProviderQualificationStatus
from .protocol import CompiledToolSet, ProviderToolCompilationError, compile_toolset


class ProviderOperation(StrEnum):
    CHAT = "chat"
    TOOL_CHAT = "tool_chat"
    VISION_INPUT = "vision_input"
    IMAGE_OUTPUT = "image_output"
    EMBEDDINGS = "embeddings"
    TRANSCRIPTION = "transcription"

    @property
    def required_capabilities(self) -> frozenset[str]:
        return {
            ProviderOperation.CHAT: frozenset({ModelCapability.CHAT.value}),
            ProviderOperation.TOOL_CHAT: frozenset(
                {ModelCapability.CHAT.value, ModelCapability.TOOLS.value}
            ),
            ProviderOperation.VISION_INPUT: frozenset(
                {ModelCapability.CHAT.value, ModelCapability.VISION.value}
            ),
            ProviderOperation.IMAGE_OUTPUT: frozenset({ModelCapability.IMAGE_OUTPUT.value}),
            ProviderOperation.EMBEDDINGS: frozenset({ModelCapability.EMBEDDINGS.value}),
            ProviderOperation.TRANSCRIPTION: frozenset({ModelCapability.TRANSCRIPTION.value}),
        }[self]


class ProviderAdmissionStatus(StrEnum):
    ADMITTED = "admitted"
    ADMITTED_UNVERIFIED = "admitted_unverified"
    NO_COMPATIBLE_MODEL = "no_compatible_model"
    CATALOG_UNAVAILABLE = "catalog_unavailable"
    CLIENT_UNAVAILABLE = "client_unavailable"
    TOOL_SCHEMA = "tool_schema"
    TOOL_CHOICE = "tool_choice"
    OPERATION_UNSUPPORTED = "operation_unsupported"
    PROVIDER_PROTOCOL = "provider_protocol"


@dataclass(frozen=True, slots=True)
class ProviderCallAdmission:
    """Private, immutable result consumed directly by provider adapters."""

    provider: str
    operation: ProviderOperation
    status: ProviderAdmissionStatus
    model: str | None
    generation_sequence: int | None
    client: Any = None
    compiled_tools: CompiledToolSet | None = None
    candidate_count: int = 0
    embedding_dimension: int | None = None

    @property
    def admitted(self) -> bool:
        return self.status in {
            ProviderAdmissionStatus.ADMITTED,
            ProviderAdmissionStatus.ADMITTED_UNVERIFIED,
        }

    @property
    def failure_code(self) -> str | None:
        if self.admitted:
            return None
        if self.status is ProviderAdmissionStatus.CLIENT_UNAVAILABLE:
            return "unavailable"
        return self.status.value


def toolset_digest(
    tools: Iterable[dict[str, Any]] | None,
    tool_choice: Any,
) -> str:
    """Return a safe cache key; neither schemas nor names leave run-private memory."""

    payload = {"tools": list(tools or ()), "choice": tool_choice}
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        encoded = "invalid"
    return sha256(encoded.encode("utf-8")).hexdigest()


def compilation_status(exc: ProviderToolCompilationError) -> ProviderAdmissionStatus:
    return {
        "tool_schema": ProviderAdmissionStatus.TOOL_SCHEMA,
        "tool_choice": ProviderAdmissionStatus.TOOL_CHOICE,
        "provider_protocol": ProviderAdmissionStatus.PROVIDER_PROTOCOL,
    }.get(exc.reason_code, ProviderAdmissionStatus.PROVIDER_PROTOCOL)


def admitted_status(source: ModelCatalogSource) -> ProviderAdmissionStatus:
    if source is ModelCatalogSource.STATIC_FALLBACK:
        return ProviderAdmissionStatus.ADMITTED_UNVERIFIED
    return ProviderAdmissionStatus.ADMITTED


def qualification_status(status: ProviderQualificationStatus) -> ProviderAdmissionStatus:
    return {
        ProviderQualificationStatus.CATALOG_UNAVAILABLE: (
            ProviderAdmissionStatus.CATALOG_UNAVAILABLE
        ),
        ProviderQualificationStatus.NO_COMPATIBLE_MODEL: (
            ProviderAdmissionStatus.NO_COMPATIBLE_MODEL
        ),
        ProviderQualificationStatus.TOOL_SCHEMA: ProviderAdmissionStatus.TOOL_SCHEMA,
        ProviderQualificationStatus.TOOL_CHOICE: ProviderAdmissionStatus.TOOL_CHOICE,
    }.get(status, ProviderAdmissionStatus.OPERATION_UNSUPPORTED)


def compile_admitted_toolset(
    *,
    provider: str,
    tools: Iterable[dict[str, Any]] | None,
    tool_choice: Any,
) -> CompiledToolSet | None:
    tool_list = list(tools or ())
    if not tool_list:
        return None
    from .registry import get_spec

    spec = get_spec(provider)
    if spec is None:
        raise ProviderToolCompilationError("provider_protocol")
    return compile_toolset(
        tool_list,
        provider=provider,
        capabilities=spec.tool_capabilities,
        tool_choice=tool_choice,
    )


__all__ = [
    "ProviderAdmissionStatus",
    "ProviderCallAdmission",
    "ProviderOperation",
    "admitted_status",
    "compilation_status",
    "compile_admitted_toolset",
    "toolset_digest",
]
