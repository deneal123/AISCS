"""Bounded opaque accounting identities, not URLs or filesystem references."""

import re

_IDENTITY = re.compile(r"[A-Za-z0-9_.:/-]+")


def safe_usage_identity(value: object, *, max_length: int = 160) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) > max_length
        or "://" in value
        or value.startswith(("/", "./"))
        or ".." in value.split("/")
        or re.match(r"^[A-Za-z]:/", value) is not None
        or _IDENTITY.fullmatch(value) is None
    ):
        return None
    return value
