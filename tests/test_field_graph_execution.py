import pytest

from service.application.field.graph_execution import FieldGraphExecution
from service.domain.contracts.field.graph import FieldGraphConfig
from tests.test_field_graph_contract import payload
from tests.test_forced_network import graph


def test_execution_rejects_wrong_graph_before_numerical_work(tmp_path):
    config = FieldGraphConfig.model_validate(payload())
    application = FieldGraphExecution(graph(), None, [])
    with pytest.raises(ValueError, match="graph"):
        application.execute(config, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_execution_verifies_export_before_return(monkeypatch, tmp_path):
    model = graph()
    raw = payload()
    raw["graph_manifest_sha256"] = "a" * 64
    model.provenance["manifest_sha256"] = "a" * 64
    config = FieldGraphConfig.model_validate(raw)
    calls = []
    monkeypatch.setattr(
        "service.application.field.graph_execution.run_field_graph_replay",
        lambda *_args, **_kwargs: {"interpretation": "one-way"},
    )
    monkeypatch.setattr(
        "service.application.field.graph_execution.export_field_graph_replay",
        lambda *_args, **_kwargs: calls.append("export") or {"files": []},
    )
    monkeypatch.setattr(
        "service.application.field.graph_execution.load_verified_field_graph_replay",
        lambda *_args: calls.append("verify"),
    )
    result = FieldGraphExecution(model, None, []).execute(config, tmp_path / "output")
    assert calls == ["export", "verify"]
    assert result["configuration_sha256"] == config.digest()


def test_current_archive_cannot_overlap_published_result(tmp_path):
    model = graph()
    raw = payload()
    model.provenance["manifest_sha256"] = raw["graph_manifest_sha256"]
    config = FieldGraphConfig.model_validate(raw)
    execution = FieldGraphExecution(model, None, [])
    for output, archive in ((tmp_path / "result", tmp_path / "result" / "currents"),
                            (tmp_path / "currents" / "result", tmp_path / "currents")):
        with pytest.raises(ValueError, match="must be separate"):
            execution.execute(config, output, current_archive_output=archive)
