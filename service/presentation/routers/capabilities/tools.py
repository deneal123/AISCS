"""Internal HTTP adapters for sidecar-owned tools.

The implementations remain in the agents service so backend callers cannot
drift from the SSRF guards and provider accounting used by normal runs.
"""

from __future__ import annotations

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from service.presentation.deps import internal_auth
from service.presentation.errors import error
from service.schemas.tools import ParseUrlRequest, PptxRequest, WebSearchRequest

router = APIRouter(prefix="/tools")


def _unavailable(_exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": "tool_unavailable", "detail": "unavailable"},
    )


@router.post("/web-search")
async def web_search_tool(
    payload: WebSearchRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    """Run the same guarded web-search implementation used by agents."""

    internal_auth(authorization)
    try:
        from service.domain.tools.web_search import web_search
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)
    query = payload.query.strip()
    return {"results": await web_search(query, num_results=payload.num_results) if query else []}


@router.post("/parse-url")
async def parse_url_tool(
    payload: ParseUrlRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    """Parse a URL through the canonical sidecar SSRF boundary."""

    internal_auth(authorization)
    try:
        from service.domain.tools.web_search import parse_url
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)
    url = payload.url.strip()
    return {"content": await parse_url(url) if url else ""}


@router.post("/pptx")
async def pptx_tool(
    payload: PptxRequest,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Retain the old route as a non-executing cutover tombstone.

    Presentation authoring now belongs exclusively to the ``pdf_gen`` Beamer
    workflow. Keeping a bounded 410 response avoids a hidden second provider,
    renderer and billing path while old internal callers are upgraded.
    """

    internal_auth(authorization)
    del payload
    return error(
        "tool_unavailable",
        "PPTX generation is retired; use the pdf_gen Beamer workflow.",
        410,
    )
