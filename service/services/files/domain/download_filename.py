"""Bounded RFC 6266 attachment names; never interpret them as filesystem paths."""

import re
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import quote


def attachment_disposition(name: str) -> str:
    """Encode UTF-8 filename* with a conservative ASCII fallback.

    The suffix is a user-facing hint, not content validation or permission to
    execute a file. This header is included in the storage signature itself.
    """
    cleaned = unicodedata.normalize("NFC", name.replace("\\", "/").rsplit("/", 1)[-1])
    cleaned = "".join(char for char in cleaned if not unicodedata.category(char).startswith("C"))
    cleaned = re.sub(r'[<>:"|?*]', "_", cleaned)
    cleaned = cleaned.strip().rstrip(". ") or "file"
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", cleaned.split(".", 1)[0], re.I):
        cleaned = "_" + cleaned
    suffix = PurePosixPath(cleaned).suffix
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix):
        suffix = ""
    if len(cleaned.encode("utf-8")) > 240:
        stem = cleaned[: -len(suffix)] if suffix else cleaned
        budget = 240 - len(suffix.encode("utf-8"))
        cleaned = stem.encode("utf-8")[:budget].decode("utf-8", errors="ignore") + suffix
    fallback = re.sub(r"[^A-Za-z0-9_. -]", "_", cleaned).strip(" ._")
    stem = fallback[: -len(suffix)] if suffix else fallback
    if not re.search(r"[A-Za-z0-9]", stem):
        fallback = "file" + suffix
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(cleaned, safe='')}"
