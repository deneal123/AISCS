from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.services.simulations.inputs.fragment_package import BASE
from service.services.simulations.inputs.fragment_source import (
    FragmentSourceUnavailable,
    owned_fragment_source,
)


class Session:
    def __init__(self, run, rows):
        self.run, self.rows, self.statements = run, rows, []

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return SimpleNamespace(scalar_one_or_none=lambda: self.run)
        return SimpleNamespace(all=lambda: self.rows)


def sample():
    graph, config = 'b' * 64, 'c' * 64
    entries = [{'name': name, 'bytes': 42, 'sha256': 'a' * 64} for name in BASE]
    manifest = {'kind': 'experimental-fragment-population', 'graph_sha256': graph,
                'configuration_sha256': config, 'files': entries}
    run = SimpleNamespace(state='completed', result={'manifest': manifest},
                          configuration_sha256=config,
                          configuration={'graph_manifest_sha256': graph})
    rows = []
    for entry in entries:
        file_id = uuid4()
        rows.append((SimpleNamespace(name=entry['name'], sha256=entry['sha256'],
                                     size=entry['bytes'], file_id=file_id),
                     SimpleNamespace(id=file_id, file_name='owned/' + entry['name'])))
    return run, rows, graph


@pytest.mark.asyncio
async def test_fragment_source_checks_ownership_and_all_artifacts():
    run, rows, graph = sample()
    session = Session(run, rows)
    source = await owned_fragment_source(session, uuid4(), uuid4(), graph)
    assert [item.name for item in source.files] == list(BASE)
    assert 'simulation_run.user_id' in str(session.statements[0])
    assert 'user_file.user_id' in str(session.statements[1])


@pytest.mark.asyncio
async def test_fragment_source_rejects_missing_wrong_graph_and_tampered_files():
    run, rows, graph = sample()
    with pytest.raises(FragmentSourceUnavailable, match='unavailable'):
        await owned_fragment_source(Session(None, rows), uuid4(), uuid4(), graph)
    with pytest.raises(FragmentSourceUnavailable, match='graph'):
        await owned_fragment_source(Session(run, rows), uuid4(), uuid4(), 'd' * 64)
    with pytest.raises(FragmentSourceUnavailable, match='missing'):
        await owned_fragment_source(Session(run, rows[:-1]), uuid4(), uuid4(), graph)
    rows[0][0].sha256 = 'd' * 64
    with pytest.raises(FragmentSourceUnavailable, match='mismatch'):
        await owned_fragment_source(Session(run, rows), uuid4(), uuid4(), graph)
