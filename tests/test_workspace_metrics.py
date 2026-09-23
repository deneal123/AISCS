from service.services.chat.presentation.routers.chat_api.workspace_metrics import (
    WorkspaceOperationMetrics,
    bounded_workspace_operation,
    bounded_workspace_status,
)


class _Labels:
    def __init__(self, calls: list[dict[str, str]]) -> None:
        self.calls = calls

    def inc(self) -> None:
        return None


class _Counter:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def labels(self, **labels: str) -> _Labels:
        self.calls.append(labels)
        return _Labels(self.calls)


def test_workspace_operation_and_status_labels_are_bounded() -> None:
    assert bounded_workspace_operation("work_snapshot") == "snapshot"
    assert bounded_workspace_operation("write_workspace_file") == "write"
    assert bounded_workspace_operation("private-marker") == "unknown"
    assert bounded_workspace_status(204) == "succeeded"
    assert bounded_workspace_status(409) == "conflict"
    assert bounded_workspace_status(410) == "expired"
    assert bounded_workspace_status(423) == "locked"
    assert bounded_workspace_status(503) == "unavailable"
    assert bounded_workspace_status("private-marker") == "unknown"


def test_workspace_metric_never_uses_unbounded_labels() -> None:
    metric = WorkspaceOperationMetrics.__new__(WorkspaceOperationMetrics)
    counter = _Counter()
    metric.operation_total = counter

    metric.record(operation="private-path", status="private-error")

    assert counter.calls == [{"operation": "unknown", "status": "unknown"}]
