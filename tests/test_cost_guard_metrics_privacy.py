"""Optional monitoring failures must not expose billing integration bodies."""

import logging
from unittest.mock import Mock

import prometheus_client
import pytest

from service.services.billing.application import cost_guard_metrics as module


@pytest.fixture
def capture(monkeypatch, caplog):
    monkeypatch.setattr(module.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(module.logger, "propagate", False)
    caplog.set_level(logging.DEBUG, logger=module.logger.name)
    return caplog


@pytest.mark.parametrize("operation", ["initialize", "increment", "gauge", "provider"])
def test_metric_failures_are_local_without_raw_traceback(monkeypatch, capture, operation):
    marker = "PRIVATE_BILLING_METRIC_BODY"
    metric = Mock()
    metric.labels.side_effect = OSError(marker)
    metric.set.side_effect = OSError(marker)
    if operation == "initialize":
        monkeypatch.setattr(prometheus_client, "Counter", Mock(side_effect=OSError(marker)))
        instance = module.CostGuardMetrics()
        assert instance.prompt_budget_stops is None
        assert instance.provider_health is None
    elif operation == "increment":
        module.CostGuardMetrics._inc(metric, provider="gigachat")
    elif operation == "gauge":
        module.CostGuardMetrics._set(metric, 1)
    else:
        instance = object.__new__(module.CostGuardMetrics)
        instance.provider_health = metric
        instance.provider("gigachat", "normal")
    assert capture.records
    assert marker not in capture.text
    assert all(record.exc_info is None for record in capture.records)
    assert all(record.component == "billing_metrics" for record in capture.records)
    assert all(record.failure_code == "unavailable" for record in capture.records)


def test_existing_metric_labels_and_provider_health_values_are_preserved():
    instance = object.__new__(module.CostGuardMetrics)
    instance.prompt_budget_stops = Mock()
    instance.pricing_fallbacks = Mock()
    instance.reservation_events = Mock()
    instance.provider_health = Mock()
    instance.prompt_budget_stop("GigaChat")
    instance.prompt_budget_stops.labels.assert_called_once_with(
        provider="gigachat", reason="prompt_budget_reached"
    )
    instance.pricing_fallback("private-provider", "private-reason")
    instance.pricing_fallbacks.labels.assert_called_once_with(provider="unknown", reason="unknown")
    instance.reservation("created")
    instance.reservation_events.labels.assert_called_once_with(outcome="created")
    instance.provider("GigaChat", "normal")
    assert instance.provider_health.labels.call_count == 3
    assert [call.kwargs for call in instance.provider_health.labels.call_args_list] == [
        {"provider": "gigachat", "status": status} for status in ("normal", "warning", "critical")
    ]
