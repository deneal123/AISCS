"""Paid acceptance must distinguish provider usage from local service-fee grants."""

import pytest

from scripts.harness.live.paid_evidence import assert_model_binding


def grant(model="GigaChat-2-Max", provider="gigachat", **kwargs):
    return {"request": {"model": model, "provider": provider, "kind": "chat", **kwargs}}


def test_local_tool_fee_does_not_change_inference_model_binding():
    assert_model_binding(
        [grant(), grant("workspace_tool", "local", kind="tool", billing_tool="workspace_tool")],
        "GigaChat-2-Max",
    )


@pytest.mark.parametrize(
    "grants",
    [
        [],
        [grant("GigaChat-3-Lightning")],
        [grant(provider="routerai")],
        [grant("workspace_tool", "local", kind="tool", billing_tool="workspace_tool")],
        [grant(), grant("GigaChat-2-Max", "gigachat", billing_tool="workspace_tool")],
        [grant(), grant("other_tool", "local", kind="tool", billing_tool="workspace_tool")],
    ],
)
def test_wrong_or_missing_inference_and_unexpected_service_fee_fail(grants):
    with pytest.raises(AssertionError):
        assert_model_binding(grants, "GigaChat-2-Max")
