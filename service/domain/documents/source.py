"""Strict model-output parser for document source generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_DENIED = re.compile(
    r"\\(?:write18|immediate\s*\\write18|openin|openout)\b|\\(?:input|include)\s*\{\s*/",
    re.IGNORECASE,
)
_PREAMBLE_IN_BODY = re.compile(
    r"\\(?:documentclass|usepackage|RequirePackage)\b|"
    r"\\(?:begin|end)\s*\{\s*document\s*\}",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AuthoredDocument:
    title: str
    main_tex: str
    references_bib: str


def _validated_document(parsed: Any) -> AuthoredDocument | None:
    if not isinstance(parsed, dict) or set(parsed) != {"title", "main_tex", "references_bib"}:
        return None
    if not all(isinstance(parsed.get(key), str) for key in parsed):
        return None
    title = parsed["title"].strip()[:300]
    main_tex = parsed["main_tex"].replace("\x00", "").strip()
    references = parsed["references_bib"].replace("\x00", "").strip()
    if not title or not (80 <= len(main_tex) <= 180_000) or len(references) > 120_000:
        return None
    if "\\documentclass" not in main_tex or "\\begin{document}" not in main_tex:
        return None
    if _DENIED.search(main_tex) or _DENIED.search(references):
        return None
    return AuthoredDocument(title, main_tex, references)


def parse_authored_document(raw: str | dict[str, Any]) -> AuthoredDocument | None:
    if isinstance(raw, dict):
        return _validated_document(raw)
    value = str(raw or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return _validated_document(parsed)


def _latex_text(value: str) -> str:
    """Escape a short title before inserting it into a trusted profile scaffold."""

    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _render_profile_source(
    payload: Any,
    *,
    scaffold_source: str,
) -> AuthoredDocument | None:
    if not isinstance(payload, dict) or set(payload) != {
        "title",
        "document_body",
        "references_bib",
    }:
        return None
    if not all(isinstance(payload.get(key), str) for key in payload):
        return None
    title = payload["title"].strip()[:300]
    body = payload["document_body"].replace("\x00", "").strip()
    references = payload["references_bib"].replace("\x00", "").strip()
    scaffold = str(scaffold_source or "").replace("\x00", "")
    marker = "\\begin{document}"
    end_marker = "\\end{document}"
    marker_at = scaffold.find(marker)
    end_at = scaffold.rfind(end_marker)
    if not title or not (1 <= len(body) <= 160_000) or len(references) > 120_000:
        return None
    if marker_at < 0 or end_at <= marker_at:
        return None
    if _DENIED.search(body) or _DENIED.search(references) or _PREAMBLE_IN_BODY.search(body):
        return None
    # The model supplies editorial content only. Page geometry, class, packages,
    # language, bibliography backend and vendor constraints remain owned by the
    # versioned profile scaffold and cannot drift between repair attempts.
    preamble = scaffold[:marker_at].rstrip()
    source = f"{preamble}\n\\title{{{_latex_text(title)}}}\n{marker}\n{body}\n{end_marker}\n"
    return _validated_document({"title": title, "main_tex": source, "references_bib": references})


def render_literal_document(scaffold_source: str, literal_text: str) -> AuthoredDocument | None:
    """Build an exact short document without a lossy model paraphrase."""

    text = str(literal_text or "").strip()
    if not text or len(text) > 1000:
        return None
    escaped_lines = [
        _latex_text(line) for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    body = (
        "\\thispagestyle{empty}\n"
        "\\begin{center}\n"
        "\\vspace*{\\fill}\n"
        "{\\Huge\\bfseries "
        + (" " + r"\\" + "\n").join(escaped_lines)
        + "}\n\\vspace*{\\fill}\n\\end{center}"
    )
    return _render_profile_source(
        {"title": "Документ", "document_body": body, "references_bib": ""},
        scaffold_source=scaffold_source,
    )


def parse_authored_tool_response(
    response: Any,
    *,
    function_name: str,
    scaffold_source: str,
) -> AuthoredDocument | None:
    """Read one forced structured-output call without accepting prose as source."""

    choices = getattr(response, "choices", None) or []
    if len(choices) != 1:
        return None
    message = getattr(choices[0], "message", None)
    calls = getattr(message, "tool_calls", None) or []
    if len(calls) != 1:
        return None
    function = getattr(calls[0], "function", None)
    if str(getattr(function, "name", "") or "") != function_name:
        return None
    arguments = getattr(function, "arguments", None)
    if isinstance(arguments, dict):
        return _render_profile_source(arguments, scaffold_source=scaffold_source)
    try:
        parsed = json.loads(str(arguments or ""))
    except (TypeError, ValueError):
        return None
    return _render_profile_source(parsed, scaffold_source=scaffold_source)
