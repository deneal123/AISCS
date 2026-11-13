import json

import pytest

from service.domain.contracts.field.graph import FieldGraphConfig
from service.infrastructure.execution.process import run_field_graph_child
from tests.test_field_graph_contract import payload


@pytest.mark.parametrize("retain", [False, True])
@pytest.mark.parametrize("retain_state", [False, True])
def test_child_publishes_requested_archive_and_cleans_work(monkeypatch, tmp_path, retain,
                                                          retain_state):
    from service.application.field import state_artifacts as field_state_artifacts
    from service.application.field.graph_execution import FieldGraphExecution
    from service.infrastructure.connectome import neighbors, synapse_repository
    from service.infrastructure.stimulation.field import graph_preview as field_graph_preview
    from service.infrastructure.stimulation.recording import current_transport

    raw = payload()
    if retain:
        raw["retain_currents"] = True
    if retain_state:
        raw["retain_state_contrast"] = True
    config = FieldGraphConfig.model_validate(raw)
    monkeypatch.setenv("GENERATOR_SYNAPSE_DIR", str(tmp_path))
    monkeypatch.setattr(neighbors, "registered_graph", lambda: object())
    monkeypatch.setattr(synapse_repository, "registered_index", lambda *_: object())

    def execute(self, _config, target, **kwargs):
        target.mkdir(parents=True)
        if retain:
            kwargs["current_archive_output"].mkdir()
        return {"manifest": {"files": []}, "current_archive_sha256": "a" * 64}

    monkeypatch.setattr(FieldGraphExecution, "execute", execute)
    monkeypatch.setattr(field_graph_preview, "export_field_graph_preview",
                        lambda *_: {"name": "field-graph-preview.json"})
    monkeypatch.setattr(field_state_artifacts, 'bundle_field_state_contrast',
                        lambda *_args, **_kwargs: [{'name': 'state-contrast.bin'}])

    def pack(work, digest, target):
        assert work.is_dir() and digest == "a" * 64
        target.write_bytes(b"archive")
        return {"bytes": 7, "sha256": "b" * 64, "manifest_sha256": digest}

    monkeypatch.setattr(current_transport, "pack_current_archive", pack)
    target = tmp_path / "execution" / "output"
    target.parent.mkdir()
    run_field_graph_child({"execution_id": "00000000-0000-0000-0000-000000000001",
                           "config": config.model_dump(mode="json")}, str(target))
    result = json.loads((target / "manifest.json").read_text())
    assert result["configuration_sha256"] == config.digest()
    assert ("current_manifest_sha256" in result) is retain
    assert (target / "currents.zip").exists() is retain
    assert any(item['name'] == 'state-contrast.bin' for item in result['files']) is retain_state
    assert not (target.parent / "current-archive-work").exists()
