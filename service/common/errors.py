"""Exception types shared across the service."""

from __future__ import annotations


class DataError(RuntimeError):
    """The on-disk knowledge base is missing or internally inconsistent."""


class CorpusError(RuntimeError):
    """Invalid corpus request: bad candidate mapping or unsafe state directory."""


class DownloadRefused(CorpusError):
    """A download was requested but policy forbids or blocks it."""
