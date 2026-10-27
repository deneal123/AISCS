"""Private receipt projection retains cost without stringifying unknown metadata."""

import json

import pytest

from service.infrastructure.agents_client.document_audit import client as document_audit


@pytest.mark.parametrize("field", ["model", "provider", "kind", "receipt_id"])
@pytest.mark.parametrize(
    "value",
    [
        {"private": "PRIVATE_BODY"},
        ["PRIVATE_BODY"],
        "https://PRIVATE_BODY.example/path",
        "name\nPRIVATE_BODY",
        "/PRIVATE_BODY/credentials",
        "C:/PRIVATE_BODY/config",
        "../PRIVATE_BODY/config",
        "model/../PRIVATE_BODY",
    ],
)
def test_untrusted_provenance_cannot_be_stringified_or_forwarded(field, value):
    item = {
        "model": "GigaChat-2-Max",
        "provider": "gigachat",
        "kind": "document_visual_audit",
        "receipt_id": "fixture-call",
        "prompt": 12,
        "completion": 3,
    }
    item[field] = value
    result = document_audit._bounded_usage({"calls": [item]})
    assert result["total"] == 15
    assert "PRIVATE_BODY" not in json.dumps(result)
    assert result["calls"][0].get(field) is None


@pytest.mark.parametrize("model", [None, "", " " * 4, "x" * 129])
def test_missing_or_invalid_model_does_not_discard_accepted_usage(model):
    result = document_audit._bounded_usage(
        {
            "calls": [
                {
                    "model": model,
                    "provider": "gigachat",
                    "prompt": 12,
                    "completion": 3,
                }
            ]
        }
    )
    assert result["total"] == 15
    assert result["calls"][0]["model"] is None
    assert "model" not in result


def test_unknown_provider_and_kind_are_omitted_without_losing_cost():
    result = document_audit._bounded_usage(
        {
            "calls": [
                {
                    "model": "GigaChat-2-Max",
                    "provider": "private_unknown_provider",
                    "kind": "private_unknown_kind",
                    "prompt": 12,
                    "completion": 3,
                }
            ]
        }
    )
    assert result["total"] == 15
    assert "provider" not in result["calls"][0]
    assert "kind" not in result["calls"][0]


@pytest.mark.parametrize("model", ["openai/gpt-4o", "vendor/model:version", "GigaChat-2-Max"])
def test_qualified_model_names_are_not_confused_with_filesystem_paths(model):
    result = document_audit._bounded_usage(
        {"calls": [{"model": model, "prompt": 12, "completion": 3}]}
    )
    assert result["model"] == model
    assert result["total"] == 15


@pytest.mark.parametrize("count", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_count_does_not_discard_other_accepted_receipts(count):
    result = document_audit._bounded_usage(
        {
            "calls": [
                {"model": "GigaChat-2-Max", "prompt": count, "completion": 3},
                {"model": "GigaChat-2-Max", "prompt": 12, "completion": 3},
            ]
        }
    )
    assert result["total"] == 15
    assert len(result["calls"]) == 1
