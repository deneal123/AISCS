"""Local STT diagnostics preserve failure semantics without response/transport bodies."""

import asyncio
import logging
import traceback
from unittest.mock import AsyncMock

import pytest

from service.infrastructure.sidecar import (
    SidecarBadRequest,
    SidecarError,
    SidecarTimeout,
    SidecarUnavailable,
)
from service.services.chat.infrastructure.media import whisper_local_transcriber as whisper

MARKER = "PRIVATE_WHISPER_AUDIO_PROXY_PROVIDER_RESPONSE_MARKER"


class Probe(whisper.WhisperLocalTranscriber):
    def __init__(self, error):
        self._lang = "ru"
        self.request_json = AsyncMock(side_effect=error)

    @property
    def enabled(self):
        return True


@pytest.fixture
def capture(monkeypatch, caplog):
    monkeypatch.setattr(whisper.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(whisper.logger, "propagate", False)
    monkeypatch.setattr(whisper.logger, "disabled", False)
    monkeypatch.setattr(whisper.logger, "level", logging.DEBUG)
    return caplog


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["models", "transcribe"])
@pytest.mark.parametrize(
    "kind,code",
    [
        (SidecarTimeout, "timeout"),
        (SidecarUnavailable, "unavailable"),
        (SidecarBadRequest, "invalid"),
        (SidecarError, "unavailable"),
    ],
)
async def test_typed_whisper_failures_have_bounded_logs(operation, kind, code, capture):
    client = Probe(kind(MARKER, MARKER, MARKER))
    if operation == "models":
        assert await client.list_models() == []
    else:
        assert await client.transcribe(b"fixture", model="base") == {}
    client.request_json.assert_awaited_once()
    assert MARKER not in capture.text
    assert len(capture.records) == 1
    record = capture.records[0]
    assert record.exc_info is None
    assert record.component == "whisper"
    assert record.failure_code == code
    assert record.operation == operation


@pytest.mark.asyncio
async def test_remote_price_refusal_keeps_type_without_detail_or_raw_cause(capture):
    client = Probe(SidecarBadRequest(MARKER, "duration_exceeded", MARKER))
    with pytest.raises(whisper.TranscriptionTooExpensive) as caught:
        await client.transcribe(b"fixture", model="base", max_duration_sec=1)
    client.request_json.assert_awaited_once()
    assert MARKER not in str(caught.value)
    assert MARKER not in caught.value.detail
    assert MARKER not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__suppress_context__
    assert not capture.records


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["models", "transcribe"])
async def test_whisper_cancellation_does_not_log_or_retry(operation, capture):
    client = Probe(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        if operation == "models":
            await client.list_models()
        else:
            await client.transcribe(b"fixture", model="base")
    client.request_json.assert_awaited_once()
    assert not capture.records


@pytest.mark.asyncio
async def test_success_path_preserves_local_stt_contract(capture):
    client = Probe(None)
    client.request_json.return_value = {"text": "fixture", "duration_sec": 2.0, "model": "base"}
    assert await client.transcribe(b"fixture", model="base", max_duration_sec=3) == {
        "text": "fixture",
        "duration_sec": 2.0,
        "model": "base",
    }
    assert client.request_json.await_args.kwargs["params"]["max_duration_sec"] == 3.0
    assert not capture.records


@pytest.mark.asyncio
async def test_disabled_whisper_does_not_make_transport_calls(monkeypatch, capture):
    monkeypatch.setattr(Probe, "enabled", property(lambda _: False))
    client = Probe(RuntimeError(MARKER))
    assert await client.list_models() == []
    assert await client.transcribe(b"fixture") == {}
    client.request_json.assert_not_awaited()
    assert not capture.records


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["technical", "cost", "cancel"])
async def test_adapter_preserves_fallback_and_cost_stop_boundaries(failure, monkeypatch, capture):
    from service.services.chat.infrastructure.media import openai_media_analysis_adapter as media

    error = {
        "technical": SidecarTimeout(MARKER, MARKER, MARKER),
        "cost": SidecarBadRequest(MARKER, "duration_exceeded", MARKER),
        "cancel": asyncio.CancelledError(),
    }[failure]
    local = Probe(error)
    monkeypatch.setattr(whisper, "WhisperLocalTranscriber", lambda: local)
    remote = AsyncMock(return_value="provider fixture")
    monkeypatch.setattr(media, "_sidecar_media", remote)
    adapter = media.OpenAIMediaAnalysisAdapter()
    if failure == "technical":
        assert await adapter.transcribe_audio(b"fixture", "fixture.wav", max_duration_sec=10) == (
            "provider fixture"
        )
        remote.assert_awaited_once()
        assert adapter.last_transcription["engine"] == "provider"
    else:
        kind = whisper.TranscriptionTooExpensive if failure == "cost" else asyncio.CancelledError
        with pytest.raises(kind):
            await adapter.transcribe_audio(b"fixture", "fixture.wav", max_duration_sec=10)
        remote.assert_not_awaited()
        assert adapter.last_transcription is None
    local.request_json.assert_awaited_once()
    assert MARKER not in capture.text
