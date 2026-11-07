import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from service.domain.contracts.replay_contract import ReplayExecutionRequest
from service.infrastructure.execution.process import Executions
from service.infrastructure.execution.replay_input import ReplayInputStore
from service.presentation.http import build_app
from tests.test_replay_contract import valid


class FakeProcess:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.alive = False
        self.exitcode = 0

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        pass

    def terminate(self):
        self.alive = False


def request(execution):
    config = valid()
    return ReplayExecutionRequest.model_validate({
        'execution_id': str(execution), 'config': config,
        'source_sha256': hashlib.sha256(b'source').hexdigest(),
        'source_description': {'manifest_sha256': config['graph_manifest_sha256']},
    })


def test_start_idempotency_and_ack_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    manager, execution = Executions(tmp_path), uuid4()
    req = request(execution)
    with pytest.raises(ValueError, match='input missing'):
        manager.start_replay(req)
    source = ReplayInputStore(tmp_path).path(execution)
    source.parent.mkdir(parents=True)
    source.write_bytes(b'source')
    record = manager.start_replay(req)
    assert record['kind'] == 'replay' and record['status'] == 'running'
    assert manager.start_replay(req) == record
    other = req.model_copy(update={'source_sha256': 'b' * 64})
    with pytest.raises(ValueError, match='another configuration'):
        manager.start_replay(other)
    process = manager.processes[str(execution)]
    process.alive = False
    output = source.parent / 'output'
    output.mkdir()
    (output / 'manifest.json').write_text(json.dumps({'kind': 'independent-cell-replay'}))
    assert manager.status(str(execution))['status'] == 'completed'
    assert manager.acknowledge(str(execution), req.config.digest())['acknowledged']
    assert not source.exists() and not output.exists()


def test_replay_start_requires_service_authorization_and_staged_input(tmp_path):
    manager = Executions(tmp_path)
    client = TestClient(build_app(manager, 'a' * 32, lambda: True))
    req = request(uuid4()).model_dump(mode='json')
    assert client.post('/v1/replay-executions', json=req).status_code == 401
    response = client.post('/v1/replay-executions', json=req,
                           headers={'Authorization': 'Bearer ' + 'a' * 32})
    assert response.status_code == 409


def test_discard_stops_replay_and_removes_its_staged_input(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    manager, execution = Executions(tmp_path), uuid4()
    req = request(execution)
    source = ReplayInputStore(tmp_path).path(execution)
    source.parent.mkdir(parents=True)
    source.write_bytes(b'source')
    manager.start_replay(req)
    result = manager.discard(str(execution), req.config.digest())
    assert result['status'] == 'cancelled' and result['discarded']
    assert not source.exists()
