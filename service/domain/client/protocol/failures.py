"""Bounded provider failure taxonomy.

Only codes from this module may cross diagnostics and trace boundaries.  Exception text,
HTTP response bodies, request payloads, schemas, and private provider state stay local.
"""

from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx


class ProviderFailureCode(StrEnum):
    TLS = "tls"
    TLS_CONFIG = "tls_config"
    AUTH = "auth"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    PAYLOAD = "payload"
    TOOL_SCHEMA = "tool_schema"
    TOOL_CHOICE = "tool_choice"
    PROTOCOL = "provider_protocol"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    REMOTE = "remote"
    SAFETY = "safety"
    CANCELLED = "cancelled"
    NO_COMPATIBLE_MODEL = "no_compatible_model"


_RETRYABLE = frozenset(
    {
        ProviderFailureCode.RATE_LIMIT,
        ProviderFailureCode.TIMEOUT,
        ProviderFailureCode.TRANSPORT,
        ProviderFailureCode.REMOTE,
    }
)


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    """Safe failure projection suitable for provider selection and observability."""

    code: ProviderFailureCode
    retryable: bool
    provider: str | None = None
    status_family: str | None = None

    def metadata(self) -> dict[str, str | bool]:
        data: dict[str, str | bool] = {
            "failure_code": self.code.value,
            "retryable": self.retryable,
        }
        if self.status_family:
            data["status_family"] = self.status_family
        return data


def _status_code(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None)
    if isinstance(value, int):
        return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _reason_code(exc: BaseException) -> str:
    value = getattr(exc, "reason_code", None)
    return str(value or "").strip().lower()


def _status_family(status: int | None) -> str | None:
    if status is None or status < 100 or status > 599:
        return None
    return f"{status // 100}xx"


def _code_from_reason(reason: str) -> ProviderFailureCode | None:
    aliases = {
        "tls": ProviderFailureCode.TLS,
        "tls_config": ProviderFailureCode.TLS_CONFIG,
        "auth": ProviderFailureCode.AUTH,
        "quota": ProviderFailureCode.QUOTA,
        "rate_limit": ProviderFailureCode.RATE_LIMIT,
        "payload": ProviderFailureCode.PAYLOAD,
        "tool_schema": ProviderFailureCode.TOOL_SCHEMA,
        "tool_choice": ProviderFailureCode.TOOL_CHOICE,
        "provider_protocol": ProviderFailureCode.PROTOCOL,
        "protocol": ProviderFailureCode.PROTOCOL,
        "timeout": ProviderFailureCode.TIMEOUT,
        "transport": ProviderFailureCode.TRANSPORT,
        "remote": ProviderFailureCode.REMOTE,
        "safety": ProviderFailureCode.SAFETY,
        "cancelled": ProviderFailureCode.CANCELLED,
        "no_compatible_model": ProviderFailureCode.NO_COMPATIBLE_MODEL,
    }
    return aliases.get(reason)


def _code_from_status(status: int | None) -> ProviderFailureCode | None:
    if status in (401, 403):
        return ProviderFailureCode.AUTH
    if status == 408:
        return ProviderFailureCode.TIMEOUT
    if status == 413:
        return ProviderFailureCode.PAYLOAD
    if status == 429:
        return ProviderFailureCode.RATE_LIMIT
    if status in (400, 404, 405, 409, 415, 422):
        return ProviderFailureCode.PAYLOAD
    if status is not None and status >= 500:
        return ProviderFailureCode.REMOTE
    return None


def classify_provider_failure(
    exc: BaseException,
    *,
    provider: str | None = None,
) -> ProviderFailure:
    """Classify without inspecting or serializing response content."""

    reason = _reason_code(exc)
    status = _status_code(exc)
    code = _code_from_reason(reason) or _code_from_status(status)
    if code is None:
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
            code = ProviderFailureCode.CANCELLED
        elif isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
            code = ProviderFailureCode.TIMEOUT
        elif isinstance(exc, (ssl.SSLError, ssl.CertificateError)):
            code = ProviderFailureCode.TLS
        elif isinstance(exc, httpx.TransportError):
            code = ProviderFailureCode.TRANSPORT
        else:
            code = ProviderFailureCode.REMOTE
    retryable = code in _RETRYABLE
    return ProviderFailure(
        code=code,
        retryable=retryable,
        provider=str(provider) if provider else None,
        status_family=_status_family(status),
    )


class ProviderProtocolError(RuntimeError):
    """Exception carrying only a bounded provider protocol failure."""

    def __init__(self, failure: ProviderFailure) -> None:
        self.failure = failure
        self.reason_code = failure.code.value
        super().__init__(failure.code.value)


def safe_failure_metadata(exc: BaseException, *, provider: str | None = None) -> dict[str, Any]:
    return classify_provider_failure(exc, provider=provider).metadata()


__all__ = [
    "ProviderFailure",
    "ProviderFailureCode",
    "ProviderProtocolError",
    "classify_provider_failure",
    "safe_failure_metadata",
]
