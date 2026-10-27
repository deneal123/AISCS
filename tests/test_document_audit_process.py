"""Only matched-namespace process identity can prove a stopped producer."""

from unittest.mock import Mock

import pytest

from service.infrastructure.document_audit import process


@pytest.mark.parametrize(
    "observed,stopped",
    [(None, True), (("Z", 10), True), (("R", 11), True), (("R", 10), False), (("T", 10), False)],
)
def test_identity_and_zombie_proof_not_elapsed_time(monkeypatch, observed, stopped):
    monkeypatch.setattr(process, "_namespace", lambda: "a" * 64)
    monkeypatch.setattr(process, "_process", lambda pid: observed)
    assert process.owner_stopped({"namespace": "a" * 64, "pid": 123, "start": 10}) is stopped


def test_other_namespace_or_missing_owner_cannot_prove_death(monkeypatch):
    read = Mock()
    monkeypatch.setattr(process, "_namespace", lambda: "b" * 64)
    monkeypatch.setattr(process, "_process", read)
    assert not process.owner_stopped({"namespace": "a" * 64, "pid": 123, "start": 10})
    assert not process.owner_stopped(None)
    read.assert_not_called()


@pytest.mark.parametrize("failure", [PermissionError(), ValueError(), IndexError()])
def test_unreadable_process_is_unknown_not_dead(monkeypatch, failure):
    monkeypatch.setattr(process, "_namespace", lambda: "a" * 64)
    monkeypatch.setattr(process, "_process", Mock(side_effect=failure))
    assert not process.owner_stopped({"namespace": "a" * 64, "pid": 123, "start": 10})
