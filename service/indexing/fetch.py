"""Bounded HTTP fetching of registered URLs; ``HTTP_FETCHER`` is the test seam."""

from __future__ import annotations

from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..common.errors import DownloadRefused

MAX_HTTP_ATTEMPTS = 2
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_TIMEOUT_S = 20.0
DEFAULT_USER_AGENT = "aspa-research-corpus/0.1 (+local draft; offline by default)"

_RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Test seam: replaceable callable with the signature of ``http_fetch``.
HTTP_FETCHER = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# download (offline by default, no search)
# ---------------------------------------------------------------------------


def http_fetch(
    url: str,
    *,
    max_attempts: int = MAX_HTTP_ATTEMPTS,
    timeout: float = DEFAULT_TIMEOUT_S,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Fetch one registered URL with a hard attempt/byte/time limit.

    Retries only transient failures. No search endpoint is ever contacted and no
    new URL is derived from a response.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise DownloadRefused(f"refusing non-http(s) URL: {url}")
    if max_attempts < 1:
        raise DownloadRefused("max_attempts must be positive")
    attempts = 0
    last_error: str | None = None
    last_status: int | None = None
    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"})
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit URL
                status = int(getattr(response, "status", 200))
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    return {
                        "ok": False,
                        "attempts": attempts,
                        "status": status,
                        "final_url": response.geturl(),
                        "content_type": response.headers.get("Content-Type"),
                        "body": None,
                        "error": "response_too_large",
                    }
                return {
                    "ok": True,
                    "attempts": attempts,
                    "status": status,
                    "final_url": response.geturl(),
                    "content_type": response.headers.get("Content-Type"),
                    "body": body,
                    "error": None,
                }
        except HTTPError as exc:
            last_status = int(exc.code)
            last_error = f"http_{exc.code}"
            if exc.code not in _RETRYABLE_HTTP_STATUS or attempt >= max_attempts:
                break
        except URLError as exc:
            last_error = f"url_error:{type(exc.reason).__name__}"
            if attempt >= max_attempts:
                break
        except TimeoutError:
            last_error = "timeout"
            if attempt >= max_attempts:
                break
    return {
        "ok": False,
        "attempts": attempts,
        "status": last_status,
        "final_url": url,
        "content_type": None,
        "body": None,
        "error": last_error or "fetch_failed",
    }


def fetch_url(url: str, **kwargs: Any) -> dict[str, Any]:
    fetcher = HTTP_FETCHER or http_fetch
    return fetcher(url, **kwargs)
