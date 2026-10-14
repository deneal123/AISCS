"""Canonical project-relative identities, shared by compiler and repair admission."""

from __future__ import annotations


def source_path(value: object) -> str:
    """Reject aliases and unsafe locations rather than resolving them into ownership."""
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        return ""
    if value.startswith("./"):
        value = value[2:]
    if (
        not value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(char in value for char in ("\\", ":"))
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or not value.endswith(".tex")
    ):
        return ""
    return value


def diagnostic_block(item: dict[str, object], provenance: dict[str, str]) -> str:
    # New reports explicitly mark unowned locations. Do not reinterpret an empty
    # source_path via legacy display paths; basename-only reports are ambiguous.
    relative = source_path(item.get("source_path", item.get("path")))
    return provenance.get(relative, "") if relative.startswith("content/") else ""
