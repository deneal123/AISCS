"""Safe operational helpers for the external LDR research engine."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .sources import normalize_url


class LDRFailureCode(StrEnum):
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    PROTOCOL = "protocol"
    CANCELLED = "cancelled"
    REMOTE = "remote"


@dataclass(frozen=True, slots=True)
class LDRFailure:
    code: LDRFailureCode
    retryable: bool

    def bounded_metadata(self) -> dict[str, str | bool]:
        return {"failure_code": self.code.value, "retryable": self.retryable}


def classify_ldr_failure(exc: BaseException) -> LDRFailure:
    reason = str(getattr(exc, "reason_code", "") or "").strip().lower()
    if isinstance(exc, asyncio.CancelledError):
        return LDRFailure(LDRFailureCode.CANCELLED, False)
    if reason == "not_configured":
        return LDRFailure(LDRFailureCode.NOT_CONFIGURED, False)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or reason == "timeout":
        return LDRFailure(LDRFailureCode.TIMEOUT, True)
    if reason in {"protocol", "invalid_response"}:
        return LDRFailure(LDRFailureCode.PROTOCOL, False)
    if reason in {"unavailable", "transport"}:
        return LDRFailure(LDRFailureCode.UNAVAILABLE, True)
    return LDRFailure(LDRFailureCode.REMOTE, True)


async def close_ldr_run(client: Any, *, timeout_sec: float = 15.0) -> LDRFailure | None:
    """Best-effort termination that never replaces the original run outcome."""

    failure: LDRFailure | None = None
    if getattr(client, "active_research_id", None):
        try:
            await asyncio.shield(
                asyncio.wait_for(client.terminate(), timeout=max(1.0, timeout_sec))
            )
        except Exception as exc:  # noqa: BLE001
            failure = classify_ldr_failure(exc)
    try:
        await client.aclose()
    except Exception as exc:  # noqa: BLE001
        failure = failure or classify_ldr_failure(exc)
    return failure


def safe_ldr_sources(sources: list[Any]) -> str:
    """Build the final-only links section without carrying arbitrary source fields."""

    lines: list[str] = []
    seen: set[str] = set()
    for source in sources or []:
        if isinstance(source, dict):
            raw_url = source.get("url") or source.get("link") or source.get("href")
            raw_title = source.get("title") or source.get("name")
        else:
            raw_url = source if isinstance(source, str) else ""
            raw_title = ""
        url = normalize_url(raw_url)
        if not url or url in seen:
            continue
        seen.add(url)
        title = re.sub(r"\s+", " ", str(raw_title or "")).strip()[:240]
        title = title.replace("[", "").replace("]", "") or f"Источник {len(lines) + 1}"
        lines.append(f"{len(lines) + 1}. [{title}]({url})")
    return ("\n\n### Источники\n" + "\n".join(lines)) if lines else ""


def ldr_usage_receipt(metrics: Any, *, default_model: str | None) -> dict[str, Any] | None:
    if not isinstance(metrics, dict):
        return None
    try:
        prompt = max(0, int(metrics.get("prompt", 0) or 0))
        completion = max(0, int(metrics.get("completion", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return None
    if prompt + completion <= 0:
        return None
    return {
        "prompt": prompt,
        "completion": completion,
        "total": prompt + completion,
        "model": str(metrics.get("model") or default_model or "") or None,
        "kind": "research_synthesis",
    }


__all__ = [
    "LDRFailure",
    "LDRFailureCode",
    "classify_ldr_failure",
    "close_ldr_run",
    "ldr_usage_receipt",
    "safe_ldr_sources",
]
