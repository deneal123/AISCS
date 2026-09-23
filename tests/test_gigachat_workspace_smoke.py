"""The opt-in workspace smoke must exercise production selection and latch code."""

from __future__ import annotations

import inspect
import io

import pytest

from service.domain.client.model_catalog import (
    ModelCatalogSource,
    ModelCatalogStatus,
    ProviderModelCatalog,
)
from service.presentation.cli import gigachat_workspace_smoke as smoke
from service.presentation.cli.gigachat_smoke_support import (
    GigaChatSmokeFailure,
    bounded_failure_code,
    require_chat_model,
)


def test_workspace_smoke_input_is_private_and_strict(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.sys,
        "stdin",
        io.StringIO(
            '{"workspace_ref":{"workspace_id":"w","token":"t","user_id":"u",'
            '"coordination_capability":"c"},"marker":"secret"}'
        ),
    )

    parsed = smoke._read_input()

    assert parsed.marker == "secret"
    assert parsed.workspace_ref["workspace_id"] == "w"


@pytest.mark.asyncio
async def test_gigachat_stream_pins_provider_but_preserves_controller_choice(monkeypatch) -> None:
    captured = {}

    async def stream(**kwargs):
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr(smoke, "stream_chat_completion", stream)
    choice = {"type": "function", "function": {"name": "selected-by-controller"}}
    chunks = [
        chunk
        async for chunk in smoke._gigachat_only_stream(
            messages=[],
            model="GigaChat-2",
            tool_choice=choice,
            pin_provider=None,
        )
    ]

    assert chunks == ["ok"]
    assert captured["pin_provider"] == "gigachat"
    assert captured["tool_choice"] is choice


def test_workspace_smoke_has_no_manual_function_forcing_path() -> None:
    source = inspect.getsource(smoke)

    assert "ToolSelectionController(" in source
    assert "GroundingLatch" in source
    assert "_forced_call" not in source
    assert "tool_choice=disclosure.tool_choice" in source


def test_workspace_read_verification_stays_internal() -> None:
    assert smoke._read_content(("not-json", '{"content":"verified"}')) == "verified"


def test_workspace_smoke_accepts_one_grounding_repair_but_not_a_retry_loop() -> None:
    smoke._validate_tool_attempts(("succeeded",))
    smoke._validate_tool_attempts(("failed", "succeeded"))

    with pytest.raises(GigaChatSmokeFailure, match="tool_count_invalid"):
        smoke._validate_tool_attempts(("failed", "failed", "succeeded"))


@pytest.mark.asyncio
async def test_live_smoke_rejects_oauth_scope_without_chat_model(monkeypatch) -> None:
    async def models(*, force_refresh=False):
        assert force_refresh is True
        return ProviderModelCatalog(
            provider="gigachat",
            models=("Embeddings", "Embeddings-2"),
            source=ModelCatalogSource.LIVE,
            status=ModelCatalogStatus.AVAILABLE,
            fresh=True,
        )

    monkeypatch.setattr(
        "service.presentation.cli.gigachat_smoke_support.gigachat._RUNTIME.model_catalog",
        models,
    )
    with pytest.raises(GigaChatSmokeFailure) as raised:
        await require_chat_model("GigaChat-2")

    assert bounded_failure_code(raised.value) == "no_compatible_model"


def test_live_smoke_diagnostics_do_not_use_exception_class_names() -> None:
    tools_source = inspect.getsource(
        __import__(
            "service.presentation.cli.gigachat_tools_smoke",
            fromlist=["gigachat_tools_smoke"],
        )
    )
    workspace_source = inspect.getsource(smoke)

    assert "type(exc).__name__" not in tools_source
    assert "type(exc).__name__" not in workspace_source
