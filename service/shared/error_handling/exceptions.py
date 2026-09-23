from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DomainError(Exception):
    message: str
    code: str = "domain_error"
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class ApplicationError(DomainError):
    status_code: int = 400


@dataclass(slots=True)
class QuotaExceededError(ApplicationError):
    """Кредиты пользователя исчерпаны → HTTP 402 Payment Required."""

    code: str = "quota_exceeded"
    status_code: int = 402


@dataclass(slots=True)
class RateLimitedError(ApplicationError):
    """Превышен лимит частоты запросов → HTTP 429 Too Many Requests."""

    code: str = "rate_limited"
    status_code: int = 429
    retry_after: int = 0
