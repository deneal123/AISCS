"""Deterministic normalization of a user's PDF request."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentBrief:
    request: str
    kind: str
    profile_id: str
    locale: str
    mode: str
    requires_bibliography: bool
    requires_placeholders: bool
    literal_text: str | None


def _literal_text(text: str) -> str | None:
    """Extract only an explicitly requested short verbatim payload."""

    quoted = re.search(
        r"(?:напиш\w*|написан\w*|текст\w*)[^\n\r\"«»]{0,80}[\"«]([^\"«»]{1,1000})[\"»]",
        text,
        re.IGNORECASE,
    )
    if quoted:
        return quoted.group(1).strip() or None
    exact = re.search(
        r"(?:написан\w*\s+ровно|напиш\w*\s+ровно|текст\w*\s+ровно)\s*:\s*([^\r\n]{1,1000})\s*$",
        text,
        re.IGNORECASE,
    )
    return exact.group(1).strip() if exact and exact.group(1).strip() else None


def normalize_brief(request: str) -> DocumentBrief:
    text = str(request or "").strip()[:24_000]
    lowered = text.casefold()
    if re.search(r"\b(презентац|слайд|deck|beamer)\w*", lowered):
        kind, profile = "presentation", "beamer_16_9"
    elif re.search(r"\b(договор|акт|претензи|юрид|legal|contract)\w*", lowered):
        kind, profile = "legal", "legal_ru"
    elif "ieee" in lowered:
        kind, profile = "article", "ieee_journal"
    elif "aaai" in lowered:
        kind, profile = "article", "aaai_conference"
    elif re.search(r"\b(стать|article|paper|исследован)\w*", lowered):
        kind, profile = "article", "generic_article"
    elif re.search(r"\b(техническ\w* задани|отч[её]т|report|specification)\w*", lowered):
        kind, profile = "report", "generic_report"
    else:
        kind, profile = "generic", "generic_document"
    english_requested = re.search(r"\b(in english|english version|английск)\w*", lowered)
    locale = "en-US" if english_requested else "ru-RU"
    mode = "submission" if kind == "article" else "camera_ready"
    return DocumentBrief(
        request=text,
        kind=kind,
        profile_id=profile,
        locale=locale,
        mode=mode,
        requires_bibliography=kind == "article",
        requires_placeholders=kind == "legal",
        literal_text=_literal_text(text) if kind == "generic" else None,
    )
