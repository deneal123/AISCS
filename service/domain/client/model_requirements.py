"""Provider-neutral requirements for selecting a chat model.

Requirements are derived before provider selection.  They describe capabilities the
accepted model must actually have; callers must never remove tools or image input to
make an otherwise incompatible provider appear usable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .model_catalog import ModelCatalogSource, ModelCatalogStatus

_IMAGE_BLOCK_TYPES = frozenset({"image", "image_url", "input_image"})


class ProviderQualificationStatus(StrEnum):
    """Bounded outcomes shared with qualification metrics and protocol parity."""

    COMPATIBLE = "compatible"
    COMPATIBLE_UNVERIFIED = "compatible_unverified"
    NO_COMPATIBLE_MODEL = "no_compatible_model"
    CATALOG_UNAVAILABLE = "catalog_unavailable"
    TOOL_SCHEMA = "tool_schema"
    TOOL_CHOICE = "tool_choice"
    UNKNOWN = "unknown"


def _contains_image(value: Any) -> bool:
    """Return whether an OpenAI-shaped message value contains image input."""

    if isinstance(value, Mapping):
        block_type = str(value.get("type") or "").strip().lower()
        if block_type in _IMAGE_BLOCK_TYPES:
            return True
        if "image_url" in value:
            return True
        return any(_contains_image(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_image(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class ModelRequirement:
    """Capabilities required from a provider/model pair for one logical call."""

    chat: bool = True
    tools: bool = False
    vision: bool = False

    @classmethod
    def from_call(
        cls,
        *,
        messages: Iterable[Mapping[str, Any]] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
    ) -> ModelRequirement:
        message_list = list(messages or ())
        return cls(
            chat=True,
            tools=bool(list(tools or ())),
            vision=any(_contains_image(message.get("content")) for message in message_list),
        )


@dataclass(frozen=True, slots=True)
class ModelQualification:
    """Decision for one provider/model requirement without provider payload data."""

    provider: str
    requirement: ModelRequirement
    status: ProviderQualificationStatus
    catalog_source: ModelCatalogSource
    catalog_status: ModelCatalogStatus
    candidate_count: int
    model: str | None = None

    @property
    def compatible(self) -> bool:
        return self.status in {
            ProviderQualificationStatus.COMPATIBLE,
            ProviderQualificationStatus.COMPATIBLE_UNVERIFIED,
        }


__all__ = ["ModelQualification", "ModelRequirement", "ProviderQualificationStatus"]
