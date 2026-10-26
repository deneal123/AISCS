"""Deterministic decoding of text payloads without touching the environment."""

from __future__ import annotations


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Decode common encodings deterministically, without touching the environment."""
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace"), "latin-1"
