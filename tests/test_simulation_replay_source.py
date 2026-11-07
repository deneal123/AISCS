from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.services.simulations.inputs.replay_source import ReplaySourceUnavailable, owned_replay_source


class Session:
    def __init__(self, run, row):
        self.run, self.row, self.statements = run, row, []

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return SimpleNamespace(scalar_one_or_none=lambda: self.run)
        return SimpleNamespace(first=lambda: self.row)


def sample():
    file_id = uuid4()
    sha, graph, size = 'a' * 64, 'b' * 64, 42
    desc = {'manifest_sha256': graph, 'binary': {'bytes': size}}
    manifest = {'connectome': {'manifest_sha256': graph},
                'files': [{'name': 'connectome.bin', 'sha256': sha, 'bytes': size}]}
    run = SimpleNamespace(state='completed', result={'preview': {'connectome': desc},
                                                      'manifest': manifest})
    artifact = SimpleNamespace(sha256=sha, size=size, file_id=file_id)
    file = SimpleNamespace(id=file_id, file_name='simulations/connectome.bin')
    return run, (artifact, file), graph


@pytest.mark.asyncio
async def test_source_requires_owner_on_run_and_file():
    run, row, graph = sample()
    session = Session(run, row)
    source = await owned_replay_source(session, uuid4(), uuid4(), graph)
    assert source.file_id == row[1].id and source.sha256 == 'a' * 64
    assert 'simulation_run.user_id' in str(session.statements[0])
    assert 'user_file.user_id' in str(session.statements[1])


@pytest.mark.asyncio
async def test_source_rejects_missing_or_inconsistent_artifacts():
    run, row, graph = sample()
    with pytest.raises(ReplaySourceUnavailable, match='unavailable'):
        await owned_replay_source(Session(None, row), uuid4(), uuid4(), graph)
    with pytest.raises(ReplaySourceUnavailable, match='graph_mismatch'):
        await owned_replay_source(Session(run, row), uuid4(), uuid4(), 'c' * 64)
    with pytest.raises(ReplaySourceUnavailable, match='missing'):
        await owned_replay_source(Session(run, None), uuid4(), uuid4(), graph)
    row[0].sha256 = 'c' * 64
    with pytest.raises(ReplaySourceUnavailable, match='mismatch'):
        await owned_replay_source(Session(run, row), uuid4(), uuid4(), graph)
