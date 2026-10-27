"""One explicit origin policy for credentialed HTTP and browser WebSockets."""

from urllib.parse import urlsplit


def allowed_cors_origins(settings) -> list[str]:
    configured = getattr(getattr(settings, "cors", None), "allow_origins", [])
    if configured:
        return list(configured)
    if str(getattr(getattr(settings, "auth", None), "auth_mode", "prod")).strip().lower() == "dev":
        return [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ]
    return []


def _origin(value: str):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        return (
            parsed.scheme,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
    except (TypeError, ValueError):
        return None


def websocket_origin_allowed(origin: str | None, settings) -> bool:
    # Non-browser authenticated clients may omit Origin. A browser supplying an
    # Origin must match the credentialed HTTP allowlist, never a wildcard.
    if origin is None:
        return True
    candidate = _origin(origin)
    return candidate is not None and any(
        candidate == _origin(allowed) for allowed in allowed_cors_origins(settings)
    )
