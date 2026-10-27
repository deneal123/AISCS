"""Closed attachment media types, independent of host MIME/registry configuration."""

from pathlib import PurePosixPath

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    **dict.fromkeys((".txt", ".md", ".tex", ".bib", ".cls", ".sty"), "text/plain; charset=utf-8"),
}


def attachment_media_type(name: str) -> str:
    """An extension is a presentation hint, never content validation.

    Unknown and executable formats stay binary attachments. Neither filenames
    nor guessed host MIME values may become arbitrary response-header values.
    """
    leaf = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = PurePosixPath(leaf).suffix.lower()
    return _MEDIA_TYPES.get(suffix, "application/octet-stream")
