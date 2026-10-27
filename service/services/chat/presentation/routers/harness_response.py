"""Private wire failures must not be rewrapped by public API exception handlers."""

from fastapi.responses import JSONResponse

PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}


def private_failure(code: str, status: int) -> JSONResponse:
    return JSONResponse({"detail": {"code": code}}, status_code=status, headers=PRIVATE_HEADERS)
