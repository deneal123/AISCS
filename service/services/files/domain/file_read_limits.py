"""Shared bounds for prefix reads across storage and application adapters."""


def validate_head_limit(max_bytes: int) -> int:
    # bool is an int subclass; zero disables the Range header in the MinIO SDK
    # and a negative size requests the entire file from a local reader.
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("invalid_head_limit")
    return max_bytes


def normalize_file_head(value: object, max_bytes: int) -> bytes | None:
    """Admit only a binary prefix; an empty file is not an unavailable read."""
    limit = validate_head_limit(max_bytes)
    return value[:limit] if isinstance(value, bytes) else None
