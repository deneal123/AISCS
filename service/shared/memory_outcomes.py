"""Подтверждение записи памяти: отсутствие исключения не означает сохранение."""

from enum import StrEnum


class MemoryWriteResult(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
