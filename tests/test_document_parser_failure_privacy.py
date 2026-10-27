"""Document extraction failures degrade safely without private log material."""

import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from service.infrastructure.sidecar import (
    SidecarBadRequest,
    SidecarClient,
    SidecarError,
    SidecarTimeout,
    SidecarUnavailable,
)
from service.services.chat.application.use_cases.upload_file_use_case import UploadFileUseCase
from service.services.chat.infrastructure.media import opendataloader_parser as parser_module

MARKER = "PRIVATE_DOCUMENT_FILENAME_RESPONSE_MARKER"


class Probe(parser_module.OpenDataLoaderParser):
    def __init__(self, *, error=None, enabled=True, limit=100):
        self.request_json = AsyncMock(side_effect=error)
        self._enabled = enabled
        self._max_bytes = limit
        self.last_parse = {"engine": "previous"}

    @property
    def enabled(self):
        return self._enabled


@pytest.fixture
def capture(monkeypatch, caplog):
    for name in (parser_module.logger.name, "service.sidecar.opendataloader"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [caplog.handler])
        monkeypatch.setattr(logger, "propagate", False)
        monkeypatch.setattr(logger, "disabled", False)
        monkeypatch.setattr(logger, "level", logging.DEBUG)
    return caplog


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,code,level",
    [
        (SidecarBadRequest, "invalid", logging.INFO),
        (SidecarTimeout, "timeout", logging.WARNING),
        (SidecarUnavailable, "unavailable", logging.WARNING),
        (SidecarError, "unavailable", logging.WARNING),
    ],
)
async def test_parser_failures_are_bounded_and_return_legacy_fallback(kind, code, level, capture):
    client = Probe(error=kind(MARKER, MARKER, MARKER))
    assert await client.parse(b"fixture", MARKER + ".pdf") == ""
    assert client.last_parse is None
    client.request_json.assert_awaited_once()
    assert len(capture.records) == 1
    record = capture.records[0]
    assert MARKER not in str(record.__dict__)
    assert record.exc_info is None and record.levelno == level
    assert record.component == "opendataloader" and record.operation == "parse"
    assert record.failure_code == code


@pytest.mark.asyncio
async def test_oversize_is_bounded_without_request_or_previous_metadata(capture):
    client = Probe(limit=1)
    assert await client.parse(b"oversize", MARKER + ".pdf") == ""
    client.request_json.assert_not_awaited()
    assert client.last_parse is None
    assert len(capture.records) == 1
    record = capture.records[0]
    assert MARKER not in str(record.__dict__) and record.exc_info is None
    assert record.failure_code == "size_limit"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,content,filename",
    [
        (False, b"fixture", "test.pdf"),
        (True, b"", "test.pdf"),
        (True, b"fixture", "test.md"),
        (True, b"fixture", ""),
    ],
)
async def test_skipped_parse_does_not_reuse_prior_metadata(enabled, content, filename, capture):
    client = Probe(enabled=enabled)
    assert await client.parse(content, filename) == ""
    assert client.last_parse is None
    client.request_json.assert_not_awaited()
    assert not capture.records


@pytest.mark.asyncio
async def test_success_preserves_markdown_metadata_and_request_contract(capture):
    client = Probe()
    client.request_json.return_value = dict(
        markdown="  # Fixture\nText  ", engine="pdf", chars=14, duration_sec=1.5
    )
    assert await client.parse(b"fixture", "fixture.docx") == "# Fixture\nText"
    assert client.last_parse == dict(engine="pdf", chars=14, duration_sec=1.5)
    client.request_json.assert_awaited_once_with(
        "POST",
        "/parse",
        params={"filename": "fixture.docx"},
        content=b"fixture",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert not capture.records


@pytest.mark.asyncio
async def test_empty_response_has_no_success_metadata(capture):
    client = Probe()
    client.request_json.return_value = {"markdown": "  ", "engine": "pdf"}
    assert await client.parse(b"fixture", "fixture.pdf") == ""
    assert client.last_parse is None
    assert not capture.records


@pytest.mark.asyncio
async def test_cancel_propagates_once_without_failure_log(capture):
    client = Probe(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await client.parse(b"fixture", "fixture.pdf")
    client.request_json.assert_awaited_once()
    assert client.last_parse is None and not capture.records


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(415, "invalid"), (500, "unavailable"), (504, "timeout")])
async def test_real_transport_to_parser_has_safe_diagnostics(status, code, capture):
    client = Probe()
    SidecarClient.__init__(
        client,
        service="opendataloader",
        base_url="http://fixture.invalid",
        timeout=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, json={"error": MARKER, "detail": MARKER})
        ),
    )
    del client.request_json  # Exercise the real inherited transport.
    assert await client.parse(b"fixture", MARKER + ".pdf") == ""
    assert client.last_parse is None
    assert len(capture.records) == 2
    assert all(
        MARKER not in str(record.__dict__)
        and record.exc_info is None
        and record.failure_code == code
        for record in capture.records
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [SidecarBadRequest, SidecarTimeout, SidecarUnavailable])
async def test_parser_failure_still_uses_existing_pdf_extraction(kind, monkeypatch, capture):
    client = Probe(error=kind(MARKER, MARKER, MARKER))
    use_case = object.__new__(UploadFileUseCase)
    use_case.document_parsing_port = client
    fallback = Mock(return_value="Readable source material preserved.")
    monkeypatch.setattr(use_case, "_pypdf_text", fallback)
    text, file_type = await use_case._extract_text(MARKER + ".pdf", "application/pdf", b"fixture")
    assert text == "Readable source material preserved." and file_type == "pdf"
    client.request_json.assert_awaited_once()
    fallback.assert_called_once_with(b"fixture")
    assert MARKER not in capture.text
