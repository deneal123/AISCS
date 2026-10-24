"""Отказ различим без URL, текста запроса, ключа и тела ошибки провайдера."""

import urllib.error
from io import BytesIO
from types import SimpleNamespace

import pytest

from local_llm.service.domain.protocol.contracts import ProtocolFailure
from local_llm.service.infrastructure.llama import transport


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.HTTPError("PRIVATE_URL", 500, "PRIVATE_BODY", {}, None),
        TimeoutError("PRIVATE_BODY"),
        ValueError("PRIVATE_BODY"),
    ],
)
def test_transport_diagnostic_never_reflects_error_values(monkeypatch, caplog, failure):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(
        transport.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=fail)
    )
    with pytest.raises(ProtocolFailure, match="upstream_unavailable"):
        transport.LlamaTransport("PRIVATE_KEY")(
            "/v1/chat/completions", {"content": "PRIVATE_INPUT"}
        )
    assert "local_llm_upstream_" in caplog.text
    assert "operation=chat" in caplog.text
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize(
    "body,expected",
    [
        (b'{"error":{"message":"PRIVATE grammar rejected PRIVATE"}}', "grammar"),
        (b'{"error":{"message":"PRIVATE Failed to parse tool call"}}', "tool_parse"),
        (
            b'{"error":{"message":"The model produced output that does not match '
            b'the expected PRIVATE format"}}',
            "tool_parse",
        ),
        (b'{"error":{"message":"Invalid diff: PRIVATE"}}', "tool_parse"),
        (b'{"error":{"message":"PRIVATE context size exceeded"}}', "context_limit"),
        (b'{"error":{"message":"PRIVATE arbitrary failure"}}', "unknown"),
        (b'{"error":"PRIVATE"}', "unknown"),
        (b"PRIVATE non-json", "unknown"),
    ],
)
def test_upstream_body_is_classified_without_reflecting_private_values(body, expected):
    error = urllib.error.HTTPError("PRIVATE_URL", 500, "PRIVATE", {}, BytesIO(body))
    assert transport.failure_category(error) == expected
