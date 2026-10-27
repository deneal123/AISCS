"""Scan metrics are exported without storage locators or exception bodies."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest

from service.services.files.application.scanning import metrics as metrics_module
from service.services.files.application.scanning import service as file_scanner_service
from service.services.files.application.scanning.service import BasicFileScanner


@pytest.mark.asyncio
async def test_successful_scan_updates_exported_counter():
    labels = {"outcome": "succeeded"}
    before = REGISTRY.get_sample_value("file_scan_total", labels) or 0
    scanner = BasicFileScanner(SimpleNamespace(get_file=AsyncMock(return_value=b"fixture")))
    assert (await scanner.scan("PRIVATE_STORAGE_LOCATOR"))["status"] == "ok"
    assert REGISTRY.get_sample_value("file_scan_total", labels) == before + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["succeeded", "failed", "skipped", "cancelled"])
async def test_each_scan_records_one_bounded_outcome(monkeypatch, outcome):
    registry = CollectorRegistry()
    metrics = metrics_module.FileScanMetrics(registry=registry)
    monkeypatch.setattr(file_scanner_service, "file_scan_metrics", metrics)
    storage = SimpleNamespace(get_file=AsyncMock(return_value=b"PRIVATE_CONTENT"))
    if outcome == "failed":
        storage.get_file.side_effect = OSError("PRIVATE_EXCEPTION_BODY")
    elif outcome == "skipped":
        storage = object()
    elif outcome == "cancelled":
        storage.get_file.side_effect = asyncio.CancelledError
    scanner = BasicFileScanner(storage)
    if outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await scanner.scan("PRIVATE_STORAGE_LOCATOR")
    else:
        result = await scanner.scan("PRIVATE_STORAGE_LOCATOR")
        assert (
            result["status"]
            == {
                "succeeded": "ok",
                "failed": "error",
                "skipped": "skipped",
            }[outcome]
        )
    assert registry.get_sample_value("file_scan_total", {"outcome": outcome}) == 1
    for other in {"succeeded", "failed", "skipped", "cancelled", "unknown"} - {outcome}:
        assert registry.get_sample_value("file_scan_total", {"outcome": other}) is None
    exported = generate_latest(registry).decode()
    assert "PRIVATE_" not in exported


def test_unknown_metric_values_do_not_create_dynamic_labels_or_stringify_objects():
    registry = CollectorRegistry()
    metrics = metrics_module.FileScanMetrics(registry=registry)

    class Private:
        def __str__(self):
            raise AssertionError("private object must not be stringified")

    for value in ("PRIVATE_UNKNOWN_OUTCOME", Private(), None, {}):
        metrics.record(value)
    assert registry.get_sample_value("file_scan_total", {"outcome": "unknown"}) == 4
    assert "PRIVATE_" not in generate_latest(registry).decode()


@pytest.mark.asyncio
async def test_metric_failure_cannot_fail_a_scan_or_expose_exception(monkeypatch, caplog):
    metrics = metrics_module.FileScanMetrics(registry=CollectorRegistry())

    def failed(**_labels):
        raise OSError("PRIVATE_METRICS_BODY")

    metrics.outcome_total = SimpleNamespace(labels=failed)
    monkeypatch.setattr(file_scanner_service, "file_scan_metrics", metrics)
    monkeypatch.setattr(metrics_module.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(metrics_module.logger, "propagate", False)
    caplog.set_level(logging.DEBUG, logger=metrics_module.logger.name)
    scanner = BasicFileScanner(SimpleNamespace(get_file=AsyncMock(return_value=b"fixture")))
    assert (await scanner.scan("PRIVATE_STORAGE_LOCATOR"))["status"] == "ok"
    assert caplog.records
    assert "PRIVATE_" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_counter_initialization_failure_is_local_and_bounded(monkeypatch, caplog):
    import prometheus_client

    def failed(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_METRICS_INIT")

    monkeypatch.setattr(prometheus_client, "Counter", failed)
    monkeypatch.setattr(metrics_module.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(metrics_module.logger, "propagate", False)
    caplog.set_level(logging.DEBUG, logger=metrics_module.logger.name)
    metrics = metrics_module.FileScanMetrics(registry=CollectorRegistry())
    metrics.record("succeeded")
    assert metrics.outcome_total is None
    assert "PRIVATE_" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
