from types import SimpleNamespace
from uuid import UUID

import pytest

from service.application.replay.replay import ReplayRecordedCell
from service.domain.contracts.replay_contract import ReplayRunConfig
from service.infrastructure.stimulation.replay_export import load_verified_reference_replay
from tests.test_replay_contract import valid
from tests.test_replay_export import replay


def test_application_binds_authorized_run_and_export(monkeypatch, tmp_path):
    cfg = ReplayRunConfig.model_validate(valid())
    graph = SimpleNamespace(provenance={'manifest_sha256': cfg.graph_manifest_sha256})
    called = []
    def compute(*args, **kwargs):
        called.append((args, kwargs))
        return replay()
    monkeypatch.setattr('service.application.replay.replay.execute_all_incoming_replay', compute)
    app = ReplayRecordedCell(graph, object(), [tmp_path])
    result = app.execute(cfg, source_run_id=cfg.source_run_id, source_binary=b'data',
                         source_description={'manifest_sha256': cfg.graph_manifest_sha256},
                         source_sha256='a' * 64, output=tmp_path / 'output')
    assert result['configuration_sha256'] == cfg.digest()
    assert called[0][1]['electrode_um'] == cfg.simulation.electrode_um
    evidence = load_verified_reference_replay(tmp_path / 'output')['evidence']
    assert evidence['request']['source_run_id'] == str(cfg.source_run_id)
    assert evidence['request']['configuration_sha256'] == cfg.digest()


def test_application_rejects_wrong_run_or_graph_before_execution(tmp_path):
    cfg = ReplayRunConfig.model_validate(valid())
    graph = SimpleNamespace(provenance={'manifest_sha256': cfg.graph_manifest_sha256})
    app = ReplayRecordedCell(graph, object(), [tmp_path])
    kwargs = {'source_binary': b'', 'source_sha256': 'a' * 64, 'output': tmp_path / 'output'}
    with pytest.raises(ValueError, match='source run'):
        app.execute(cfg, source_run_id=UUID('00000000-0000-4000-8000-000000000002'),
                    source_description={'manifest_sha256': cfg.graph_manifest_sha256}, **kwargs)
    with pytest.raises(ValueError, match='graph'):
        app.execute(cfg, source_run_id=cfg.source_run_id,
                    source_description={'manifest_sha256': 'wrong'}, **kwargs)
    assert not (tmp_path / 'output').exists()
