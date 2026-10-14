"""Shared closed font diagnostics for sidecar and disposable PDF compiler."""

from __future__ import annotations

import re

_FONT_TYPES = (
    "cid type 0c (ot)",
    "cid truetype (ot)",
    "type 1c (ot)",
    "cid type 0c",
    "cid truetype",
    "cid type 0",
    "type 1c",
    "truetype",
    "type 1",
    "type 3",
)
_HEADER = "name type encoding emb sub uni object id"
_MAX_REPORT_CHARS = 4 * 1024 * 1024
_MAX_FONT_ROWS = 10_000


def font_diagnostics(report: str) -> tuple[tuple[str, int], ...]:
    """Parse from right: embedding flags precede both object and generation IDs.

    Font names, encodings and IDs are never retained or emitted in diagnostics.
    A valid header-only report is allowed for an image/vector-only PDF; a failed
    or malformed report is not equivalent to proving that no fonts were used.
    """

    if not isinstance(report, str) or len(report) > _MAX_REPORT_CHARS:
        return (("font_unavailable", 1),)
    lines = [line.strip() for line in report.splitlines() if line.strip()]
    if (
        len(lines) < 2
        or " ".join(lines[0].split()).casefold() != _HEADER
        or not lines[1]
        or set(lines[1]) - {"-", " "}
        or len(lines) - 2 > _MAX_FONT_ROWS
    ):
        # Preserve the legacy synthetic Type 3 sentinel, but never treat a
        # malformed table as an authoritative clean font inventory.
        return (
            (("type3_font", 1), ("font_unavailable", 1))
            if "type 3" in report.casefold()
            else (("font_unavailable", 1),)
        )
    unembedded = type3 = 0
    for line in lines[2:]:
        fields = line.split()
        if len(fields) < 8 or not all(re.fullmatch(r"[0-9]+", item) for item in fields[-2:]):
            return (("font_unavailable", 1),)
        flags = fields[-5:-2]
        if any(item not in {"yes", "no"} for item in flags):
            return (("font_unavailable", 1),)
        # Match the longest known suffix, so spaces/Type 3 in a font name do not
        # override the actual type column (for example CID TrueType).
        prefix = " ".join(fields[:-6]).casefold()
        kind = next((value for value in _FONT_TYPES if prefix.endswith(" " + value)), None)
        if kind is None:
            return (("font_unavailable", 1),)
        unembedded += flags[0] == "no"
        type3 += kind == "type 3"
    return tuple(
        (code, min(count, 999))
        for code, count in (("font_not_embedded", unembedded), ("type3_font", type3))
        if count
    )
