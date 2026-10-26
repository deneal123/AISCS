"""Source identifier helpers."""

from __future__ import annotations


def source_number(source_id: str) -> int:
    return int(source_id[1:])
