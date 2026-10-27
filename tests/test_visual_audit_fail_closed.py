"""A malformed negative vision result must never become a positive attestation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.client.protocol.failures import (
    ProviderFailure,
    ProviderFailureCode,
    ProviderProtocolError,
)
from service.domain.documents import visual_audit as audit
from service.domain.integration_failure import IntegrationFailureCode


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("boundary", "failure", "code"),
    [
        ("qualification", TimeoutError("PRIVATE_MARKER https://private.invalid"), "timeout"),
        ("raster", audit.WorkspaceUnavailable(IntegrationFailureCode.TIMEOUT), "timeout"),
        (
            "provider",
            ProviderProtocolError(ProviderFailure(ProviderFailureCode.AUTH, False)),
            "auth",
        ),
        ("protocol", ValueError("PRIVATE_MARKER https://private.invalid"), "invalid"),
    ],
)
async def test_failure_diagnostics_preserve_only_closed_boundary(
    monkeypatch, caplog, boundary, failure, code
):
    monkeypatch.setattr(audit, "require_execution", lambda value: value)
    monkeypatch.setattr(
        audit,
        "list_qualified_models",
        AsyncMock(
            side_effect=failure if boundary == "qualification" else None,
            return_value=["vision-model"],
        ),
    )
    monkeypatch.setattr(audit, "pick_text_model", lambda _models: "vision-model")
    monkeypatch.setattr(
        audit,
        "call",
        AsyncMock(
            return_value={
                "audit": {
                    "page_count": 1,
                    "source_digest": "a" * 64,
                    "artifact_sha256": "b" * 64,
                }
            }
        ),
    )
    monkeypatch.setattr(
        audit,
        "download_binary",
        AsyncMock(
            side_effect=failure if boundary == "raster" else None,
            return_value=(b"png", {}),
        ),
    )
    monkeypatch.setattr(
        audit,
        "invoke_model_call",
        AsyncMock(
            side_effect=failure if boundary == "provider" else None,
            return_value=SimpleNamespace(response=None),
        ),
    )
    monkeypatch.setattr(audit, "_audit_tool_arguments", lambda _response: {})
    monkeypatch.setattr(audit, "_parse_result", lambda *_args: (_ for _ in ()).throw(failure))
    report = AsyncMock(return_value={"state": "visual_pending"})
    monkeypatch.setattr(audit, "_report", report)
    result = await audit.audit_document_build(
        {}, "PRIVATE_BUILD", execution=SimpleNamespace(provider_snapshot=None)
    )
    assert result.retryable and not result.passed
    assert f"stage={boundary} code={code}" in caplog.text
    assert "PRIVATE" not in caplog.text and "https://" not in caplog.text
    assert report.await_count == 1


@pytest.mark.asyncio
async def test_qualification_timeout_returns_private_bounded_reply_with_zero_usage(monkeypatch):
    from service.presentation.routers.capabilities import document_audit as endpoint

    monkeypatch.setattr(endpoint, "internal_auth", lambda _authorization: None)
    monkeypatch.setattr(
        audit,
        "call",
        AsyncMock(
            return_value={
                "audit": {
                    "page_count": 1,
                    "source_digest": "a" * 64,
                    "artifact_sha256": "b" * 64,
                }
            }
        ),
    )
    monkeypatch.setattr(
        audit,
        "list_qualified_models",
        AsyncMock(
            side_effect=TimeoutError("PRIVATE_MARKER https://private.invalid"),
        ),
    )
    report = AsyncMock(return_value={"state": "visual_pending"})
    monkeypatch.setattr(audit, "_report", report)
    result = await endpoint.audit_document(
        endpoint.DocumentAuditRequest(build_id="fixture-build", workspace_ref={}),
        authorization="fixture-auth",
    )
    assert result["status"] == "vision_unavailable"
    assert not result["passed"] and result["retryable"]
    assert result["usage"]["total"] == 0 and result["usage"]["calls"] == []
    assert "PRIVATE_MARKER" not in repr(result)
    report.assert_awaited_once()


@pytest.mark.parametrize(
    "payload",
    [
        {"passed": False, "issues": []},
        {"passed": True, "issues": [], "extra": "PRIVATE_MARKER"},
        {"passed": False, "issues": [{"code": "visual_clipping", "page": True}]},
        {
            "passed": False,
            "issues": [{"code": "visual_clipping", "page": 1, "text": "PRIVATE_MARKER"}],
        },
        {"passed": False, "issues": [{"code": "visual_clipping", "page": 1}] * 101},
    ],
)
def test_parser_rejects_ambiguous_or_unbounded_attestation(payload):
    with pytest.raises(ValueError, match="^invalid visual audit response$"):
        audit._parse_result(payload, frozenset({1}))


@pytest.mark.asyncio
async def test_negative_result_without_diagnostics_never_reports_passed(monkeypatch):
    execution = SimpleNamespace(provider_snapshot=None)
    monkeypatch.setattr(audit, "require_execution", lambda value: value)
    monkeypatch.setattr(audit, "list_qualified_models", AsyncMock(return_value=["vision-model"]))
    monkeypatch.setattr(audit, "pick_text_model", lambda _models: "vision-model")
    monkeypatch.setattr(
        audit,
        "call",
        AsyncMock(
            return_value={
                "audit": {"page_count": 1, "source_digest": "a" * 64, "artifact_sha256": "b" * 64}
            }
        ),
    )
    monkeypatch.setattr(audit, "download_binary", AsyncMock(return_value=(b"png", {})))
    monkeypatch.setattr(
        audit,
        "invoke_model_call",
        AsyncMock(
            return_value=SimpleNamespace(
                response=SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="submit_visual_audit",
                                            arguments={"passed": False, "issues": []},
                                        )
                                    )
                                ]
                            )
                        )
                    ]
                )
            )
        ),
    )
    report = AsyncMock(return_value={"state": "visual_pending"})
    monkeypatch.setattr(audit, "_report", report)
    result = await audit.audit_document_build({}, "opaque-build", execution=execution)
    assert result.passed is False and result.retryable is True
    assert report.await_count == 1
    assert report.await_args.kwargs["passed"] is False
    assert report.await_args.kwargs["retryable"] is True
