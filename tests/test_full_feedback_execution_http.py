import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from service.domain.contracts.population.full_feedback import FullFeedbackExecutionRequest
from service.infrastructure.execution.process import Executions
from service.presentation.http import build_app
from tests.test_full_feedback_execution import config
from tests.test_replay_execution import FakeProcess


def test_http_exposes_pause_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    monkeypatch.delenv('GENERATOR_FULL_PAUSE', raising=False)
    client = TestClient(build_app(Executions(tmp_path), 'a' * 32, lambda: True))
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    req = FullFeedbackExecutionRequest(execution_id=uuid4(), config=config())
    client.post('/v1/full-population-feedback-executions',
                json=req.model_dump(mode='json'), headers=auth)
    path = f'/v1/executions/{req.execution_id}'
    # Without a pause directory the route exists and refuses honestly, which is
    # the difference between an unsupported control and an undiscoverable one.
    assert client.post(path + '/pause', headers=auth).status_code == 409
    assert client.post(path + '/resume', headers=auth).status_code == 409
    assert client.get(path, headers=auth).status_code == 200
