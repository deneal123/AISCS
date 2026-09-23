"""Versioned, bounded intent contract for Document Forge authoring."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

from .outline import section_role
from .profile_contract import DOCUMENT_PROFILE_REQUIRED_SECTIONS

DocumentKind = Literal["generic", "article", "presentation", "legal", "report", "unsupported"]
DocumentMode = Literal["draft", "submission", "camera_ready"]
LengthClass = Literal["short", "standard", "long"]
CitationPolicy = Literal["none", "optional", "required"]
PresentationDensity = Literal["sparse", "balanced", "dense"]
_GENERIC_KIND: DocumentKind = "generic"

INTENT_SCHEMA_VERSION = 1
_PROFILE_BY_KIND: dict[str, str] = {
    "generic": "generic_document",
    "article": "generic_article",
    "presentation": "beamer_16_9",
    "legal": "legal_ru",
    "report": "generic_report",
}
_PROFILE_KIND = {
    **{value: key for key, value in _PROFILE_BY_KIND.items()},
    "ieee_journal": "article",
    "aaai_conference": "article",
}
_LITERAL = re.compile(
    r"(?:напиш\w*|текст\w*)[^\n\r\"«»]{0,80}[\"«]([^\"«»]{1,1000})[\"»]",
    re.IGNORECASE,
)
_NON_SECTION_LABELS = frozenset({"article", "body", "document", "title", "статья", "текст"})


@dataclass(frozen=True, slots=True)
class LegalField:
    name: str
    value: str | None = None
    required: bool = True


@dataclass(frozen=True, slots=True)
class DocumentIntent:
    schema_version: int
    request: str
    kind: DocumentKind
    profile_id: str
    locale: str
    mode: DocumentMode
    title: str
    audience: str
    length_class: LengthClass
    required_sections: tuple[str, ...]
    citation_policy: CitationPolicy
    presentation_density: PresentationDensity
    legal_fields: tuple[LegalField, ...]
    user_requirements: tuple[str, ...]
    literal_text: str | None = None

    @property
    def requires_bibliography(self) -> bool:
        return self.citation_policy == "required"

    @property
    def requires_placeholders(self) -> bool:
        return self.kind == "legal" and any(
            item.required and not item.value for item in self.legal_fields
        )


def literal_shortcut(request: str) -> DocumentIntent | None:
    text = str(request or "").strip()[:24_000]
    match = _LITERAL.search(text)
    if not match or len(text) > 2_000:
        return None
    literal = match.group(1).strip()
    if not literal:
        return None
    return DocumentIntent(
        schema_version=INTENT_SCHEMA_VERSION,
        request=text,
        kind=_GENERIC_KIND,
        profile_id="generic_document",
        locale="ru-RU",
        mode="camera_ready",
        title="Документ",
        audience="пользователь",
        length_class="short",
        required_sections=(),
        citation_policy="none",
        presentation_density="balanced",
        legal_fields=(),
        user_requirements=(),
        literal_text=literal,
    )


def _strings(value: Any, *, limit: int, item_limit: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    output: list[str] = []
    for item in value[:limit]:
        text = str(item or "").replace("\x00", "").strip()[:item_limit]
        if text and text not in output:
            output.append(text)
    return tuple(output)


def _mapping(raw: str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _profile_for(kind: str, requested: object) -> str | None:
    if kind == "unsupported":
        return "generic_document"
    profile = str(requested or _PROFILE_BY_KIND.get(kind, ""))
    if kind not in _PROFILE_BY_KIND or _PROFILE_KIND.get(profile) != kind:
        return None
    return profile


def _choice(value: object, *, default: str, allowed: frozenset[str]) -> str | None:
    selected = str(value or default)
    return selected if selected in allowed else None


def _legal_fields(value: object) -> tuple[LegalField, ...]:
    fields: list[LegalField] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:80]
        field_value = str(item.get("value") or "").strip()[:500] or None
        if name:
            fields.append(LegalField(name, field_value, bool(item.get("required", True))))
    return tuple(fields[:32])


def _required_sections(
    profile_sections: tuple[str, ...],
    requested_sections: tuple[str, ...],
) -> tuple[str, ...]:
    """Keep locked profile labels and add only distinct semantic user sections."""

    output = list(profile_sections)
    seen_titles = {item.strip().casefold() for item in output}
    seen_roles = {role for item in output if (role := section_role(item)) is not None}
    for item in requested_sections:
        title = item.strip()
        key = title.casefold()
        role = section_role(title)
        if not title or key in _NON_SECTION_LABELS or key in seen_titles:
            continue
        if role is not None and role in seen_roles:
            continue
        output.append(title)
        seen_titles.add(key)
        if role is not None:
            seen_roles.add(role)
    return tuple(output[:24])


def parse_document_intent(raw: str | dict[str, Any], request: str) -> DocumentIntent | None:
    """Parse strict model output without allowing it to alter locked profile facts."""

    value = _mapping(raw)
    if value is None:
        return None
    kind = str(value.get("kind") or "generic")
    profile = _profile_for(kind, value.get("profile_id"))
    if profile is None:
        return None
    locale = _choice(value.get("locale"), default="ru-RU", allowed=frozenset({"ru-RU", "en-US"}))
    mode = _choice(
        value.get("mode"),
        default="submission" if kind == "article" else "camera_ready",
        allowed=frozenset({"draft", "submission", "camera_ready"}),
    )
    length_class = _choice(
        value.get("length_class"),
        default="standard",
        allowed=frozenset({"short", "standard", "long"}),
    )
    density = _choice(
        value.get("presentation_density"),
        default="balanced",
        allowed=frozenset({"sparse", "balanced", "dense"}),
    )
    citation = _choice(
        value.get("citation_policy"),
        default="required" if kind == "article" else "none",
        allowed=frozenset({"none", "optional", "required"}),
    )
    if None in {locale, mode, length_class, density, citation}:
        return None
    if kind == "article":
        citation = "required"
    elif kind == "unsupported":
        mode = "draft"
        citation = "none"
    requested_sections = _strings(value.get("required_sections"), limit=24, item_limit=120)
    profile_sections = DOCUMENT_PROFILE_REQUIRED_SECTIONS.get(profile, ())
    return DocumentIntent(
        schema_version=INTENT_SCHEMA_VERSION,
        request=str(request or "").strip()[:24_000],
        kind=cast(DocumentKind, kind),
        profile_id=profile,
        locale=cast(str, locale),
        mode=cast(DocumentMode, mode),
        title=str(value.get("title") or "Документ").strip()[:300] or "Документ",
        audience=str(value.get("audience") or "пользователь").strip()[:300],
        length_class=cast(LengthClass, length_class),
        required_sections=_required_sections(profile_sections, requested_sections),
        citation_policy=cast(CitationPolicy, citation),
        presentation_density=cast(PresentationDensity, density),
        legal_fields=_legal_fields(value.get("legal_fields")),
        user_requirements=_strings(value.get("user_requirements"), limit=24, item_limit=300),
    )


def deterministic_intent(request: str) -> DocumentIntent:
    """Safe fallback used only when structured normalization is unavailable."""

    literal = literal_shortcut(request)
    if literal is not None:
        return literal
    text = str(request or "").strip()[:24_000]
    return DocumentIntent(
        schema_version=INTENT_SCHEMA_VERSION,
        request=text,
        kind=_GENERIC_KIND,
        profile_id="generic_document",
        locale="ru-RU",
        mode="draft",
        title="Документ",
        audience="пользователь",
        length_class="standard",
        required_sections=(),
        citation_policy="none",
        presentation_density="balanced",
        legal_fields=(),
        user_requirements=(),
    )


__all__ = [
    "CitationPolicy",
    "DocumentIntent",
    "DocumentKind",
    "DocumentMode",
    "INTENT_SCHEMA_VERSION",
    "LegalField",
    "deterministic_intent",
    "literal_shortcut",
    "parse_document_intent",
]
