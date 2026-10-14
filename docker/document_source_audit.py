"""Bounded authored-input audit, not a general TeX interpreter.

The engine recorder is authoritative after compilation. A literal input graph is
available for pre-compile callers. Neither path scans unrelated project files.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

MAX_SOURCE_AUDIT_BYTES = 4 * 1024 * 1024
MAX_SOURCE_AUDIT_FILES = 512
_EXCLUDED = {".git", ".gpthub-document", "artifacts", "vendor", "__pycache__"}
_INPUT = re.compile(r"\\(?:input|include)\b\s*(?:\{([^{}]+)\}|([^\s{}\\]+))")
_LITERAL_ENV = re.compile(r"\\begin\s*\{(verbatim\*?|Verbatim|lstlisting|minted|comment)\}")
_VERB = re.compile(r"\\verb\*?([^\w\s])")
_CITATION = re.compile(
    r"\\(?:cite[pt]?|citealp|citealt|citeauthor|citeyear(?:par)?|"
    r"(?:auto|paren|text|foot|super|smart)cite)\*?\s*"
    r"(?:\[[^\]\r\n]{0,1024}\]\s*){0,2}\{([^{}\r\n]{1,2048})\}"
)
_HEADING = re.compile(
    r"\\(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph|frametitle)"
    r"\*?\s*(?:\[[^\]]*\]\s*)?\{([^{}]+)\}"
)


class SourceAuditFailure(ValueError):
    def __init__(self) -> None:
        super().__init__("source_audit_unavailable")


def active_tex(source: str) -> str:
    """Mask comments and literal listings while preserving newlines and escapes."""

    parts: list[str] = []
    index = 0
    while index < len(source):
        if source[index] == "%":
            end = source.find("\n", index)
            index = len(source) if end < 0 else end
        elif source[index] == "\\":
            literal = _LITERAL_ENV.match(source, index)
            verb = _VERB.match(source, index)
            if literal:
                closing = re.search(
                    r"\\end\s*\{" + re.escape(literal.group(1)) + r"\}",
                    source[literal.end() :],
                )
                if closing is None:
                    raise SourceAuditFailure()
                end = literal.end() + closing.end()
                parts.append("\n" * source[index:end].count("\n"))
                index = end
            elif verb:
                end = source.find(verb.group(1), verb.end())
                if end < 0 or "\n" in source[verb.end() : end]:
                    raise SourceAuditFailure()
                parts.append(" ")
                index = end + 1
            else:
                # Consuming both backslashes makes \\% a real comment, while
                # \% remains literal and cannot hide an active placeholder.
                parts.append(source[index : index + 2])
                index += 2
        else:
            parts.append(source[index])
            index += 1
    return "".join(parts)


def _path(root: Path, name: str) -> Path | None:
    try:
        candidate = (root / name).resolve()
        relative = candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if candidate.suffix.lower() != ".tex" or any(
        part in _EXCLUDED or part.startswith(".") for part in relative.parts
    ):
        return None
    return candidate


def _read(path: Path, limit: int) -> str:
    try:
        with path.open("rb") as stream:
            value = stream.read(limit + 1)
    except OSError:
        raise SourceAuditFailure() from None
    if len(value) > limit:
        raise SourceAuditFailure()
    try:
        return value.decode("utf-8")
    except UnicodeError:
        raise SourceAuditFailure() from None


def authored_source(project: Path, entrypoint: str = "main.tex") -> str:
    root = project.resolve()
    main = _path(root, entrypoint)
    if main is None:
        raise SourceAuditFailure()
    recorder = main.with_suffix(".fls")
    selected = [main]
    recorded = recorder.is_file()
    if recorded:
        inventory = _read(recorder, MAX_SOURCE_AUDIT_BYTES)
        selected = []
        for line in inventory.splitlines():
            if line.startswith("INPUT "):
                path = _path(root, line[6:])
                if path is not None and path not in selected:
                    selected.append(path)
                    if len(selected) > MAX_SOURCE_AUDIT_FILES:
                        raise SourceAuditFailure()
        if main not in selected:
            raise SourceAuditFailure()
    parts: list[str] = []
    visited: set[Path] = set()
    remaining = MAX_SOURCE_AUDIT_BYTES
    while selected:
        path = selected.pop(0)
        if path in visited:
            continue
        visited.add(path)
        if len(visited) > MAX_SOURCE_AUDIT_FILES:
            raise SourceAuditFailure()
        source = _read(path, remaining)
        remaining -= len(source.encode("utf-8"))
        active = active_tex(source)
        parts.append(active)
        if not recorded:
            for match in _INPUT.finditer(active):
                name = (match.group(1) or match.group(2)).strip()
                if "\\" in name:
                    # Macro-computed names need a real engine recorder.
                    raise SourceAuditFailure()
                if not Path(name).suffix:
                    name += ".tex"
                target = _path(root, name)
                if target is None:
                    raise SourceAuditFailure()
                if target not in visited and target not in selected:
                    selected.append(target)
                    if len(visited) + len(selected) > MAX_SOURCE_AUDIT_FILES:
                        raise SourceAuditFailure()
    return "\n".join(parts)


def section_titles(source: str) -> set[str]:
    return {" ".join(match.group(1).split()).casefold() for match in _HEADING.finditer(source)}


def has_citation(source: str) -> bool:
    """Recognize bounded standard LaTeX/natbib/biblatex citation syntax.

    The caller supplies active authored input, with comments/listings removed.
    This proves citation intent only; the compiler/evidence registry still own
    resolution and provenance. Unknown macros and empty key lists do not qualify.
    """
    return any(
        all(key.strip() for key in match.group(1).split(","))
        for match in _CITATION.finditer(source)
    )


def _legal_requirements(intent: dict, publication: bool) -> list[dict[str, object]]:
    fields = intent.get("legal_fields", [])
    if not isinstance(fields, list) or len(fields) > 32:
        raise SourceAuditFailure()
    unresolved = 0
    for field in fields:
        if not isinstance(field, dict):
            raise SourceAuditFailure()
        name, value, required = field.get("name"), field.get("value"), field.get("required")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 80
            or type(required) is not bool
            or (value is not None and (not isinstance(value, str) or len(value) > 500))
        ):
            raise SourceAuditFailure()
        if required and (value is None or not value.strip()):
            unresolved += 1
    return (
        [
            {
                "severity": "error" if publication else "warning",
                "code": "unresolved_placeholder",
                "count": unresolved,
            }
        ]
        if unresolved
        else []
    )


def authoring_manifest_audit(
    project: Path,
    profile_id: str,
    publication: bool = True,
) -> list[dict[str, object]]:
    path = project / ".gpthub-authoring.json"
    if not path.is_file():
        return []
    invalid = [{"severity": "error", "code": "authoring_invalid", "count": 1}]
    try:
        raw = json.loads(_read(path, MAX_SOURCE_AUDIT_BYTES))
        if (
            not isinstance(raw, dict)
            or type(raw.get("schema_version")) is not int
            or raw["schema_version"] != 1
        ):
            return invalid
        version = raw.get("draft_version")
        if type(version) is not int or not 1 <= version <= 1_000_000:
            return invalid
        if set(raw) == {"schema_version", "draft_version", "draft_digest"}:
            # Raw-source publication has an identity, but no semantic intent.
            digest = raw.get("draft_digest")
            return (
                [] if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) else invalid
            )
        draft = raw.get("draft")
        if (
            not isinstance(draft, dict)
            or type(draft.get("version")) is not int
            or draft["version"] != version
        ):
            return invalid
        blocks = draft.get("blocks")
        intent = raw.get("intent", {})
        if (
            raw.get("profile_id") != profile_id
            or not isinstance(intent, dict)
            or not isinstance(blocks, list)
            or len(blocks) > 2048
            or not all(isinstance(block, dict) for block in blocks)
        ):
            return invalid
        encoded = json.dumps(
            draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        if hashlib.sha256(encoded).hexdigest() != raw.get("draft_digest"):
            return invalid
        required = intent.get("required_sections", [])
        if (
            not isinstance(required, list)
            or len(required) > 24
            or not all(isinstance(item, str) and item.strip() for item in required)
        ):
            return invalid
        headings = set()
        for block in blocks:
            if block.get("kind") in {"section", "slide"}:
                title = block.get("title") or block.get("text") or ""
                if not isinstance(title, str):
                    return invalid
                headings.add(title.strip().casefold())
        missing = sum(section.strip().casefold() not in headings for section in required)
        diagnostics = (
            [{"severity": "error", "code": "required_section", "count": missing}] if missing else []
        )
        return diagnostics + _legal_requirements(intent, publication)
    except (SourceAuditFailure, TypeError, ValueError):
        return invalid
