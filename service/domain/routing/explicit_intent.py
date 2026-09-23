"""Deterministic routing for explicitly requested user artifacts."""

from __future__ import annotations

import re

_DOCUMENT_ACTION_RE = re.compile(
    r"\b(созда(?:й|йте|ть)|сдела(?:й|йте|ть)|сгенерир\w*|подготов\w*|напиш\w*|"
    r"оформ\w*|собер\w*|create|generate|prepare|write|build|render)\b",
    re.I,
)
_DOCUMENT_OUTPUT_RE = re.compile(
    r"(?:\.pdf\b|\bpdf\b|\.tex\b|\blatex\b|\bстать[ьюия]\w*\b|\bпрезентац\w*\b|"
    r"\bслайд\w*\b|\bюридическ\w*\s+документ\w*\b|\barticle\b|\bpresentation\b|"
    r"\bslide\s*deck\b|\blegal\s+document\b)",
    re.I,
)


def explicit_requested_tool(text: str) -> str | None:
    """Return a route only for an unambiguous user-requested artifact.

    This is policy evidence, not semantic guessing. Topic mentions and review
    requests intentionally return ``None``; creation requests may reach the
    backend reservation gate before any document work starts.
    """

    value = str(text or "")
    if _DOCUMENT_ACTION_RE.search(value) and _DOCUMENT_OUTPUT_RE.search(value):
        return "pdf_gen"
    return None


__all__ = ["explicit_requested_tool"]
