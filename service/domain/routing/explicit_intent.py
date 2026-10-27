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
    # Video transcripts belong to the confirmed video workflow, not the generic
    # PDF author. This is an exclusion from the PDF decision, not a route result.
    video_transcript = bool(
        re.search(
            r"(?:транскрипц\w*|транскрипт\w*|транскрибир\w*|расшифров\w*|"
            r"transcri(?:be|pt(?:ion)?|bing))",
            value,
            re.I,
        )
        and re.search(r"youtube\.com|youtu\.be|vimeo\.com|rutube\.ru", value, re.I)
    )
    if not _DOCUMENT_ACTION_RE.search(value) or not _DOCUMENT_OUTPUT_RE.search(value):
        return None
    if video_transcript:
        return None

    explicit_format = re.search(
        r"(?:\.pdf\b|\bpdf\b|\.tex\b|\blatex\b|\bdocx\b|\.docx\b|\bword\b)",
        value,
        re.I,
    )
    explicit_file_action = re.search(
        r"(?:\bfile\b|\bфайл\w*\b|\bформат\w*\b|\bэкспорт\w*\b|"
        r"\bскача\w*\b|\bсохран\w*\b|\bdocument\b|\bdocumento\b|\bдокумент\w*\b)",
        value,
        re.I,
    )
    if explicit_format or explicit_file_action:
        return "pdf_gen"

    # Articles alone normally request chat prose; presentations are document requests.
    asks_presentation = re.search(
        r"(?:\bпрезентац\w*\b|\bслайд\w*\b|\bpresentation\b|\bslide\s*deck\b)",
        value,
        re.I,
    )
    asks_article = re.search(r"(?:\bстать[ьюия]\w*\b|\barticle\b)", value, re.I)
    if asks_presentation:
        return "pdf_gen"
    if asks_article:
        return None
    return None


__all__ = ["explicit_requested_tool"]
