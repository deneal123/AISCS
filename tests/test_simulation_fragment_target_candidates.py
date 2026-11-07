import hashlib
import json
from types import SimpleNamespace

import pytest

from service.services.simulations.inputs.fragment_target_candidates import fragment_target_candidates


@pytest.mark.asyncio
async def test_candidate_events_are_bound_to_verified_source_and_target():
    configuration = {'source_ids': [10, 11], 'simulation': {'duration_ms': 10}}
    manifest = {'configuration_sha256': 'a' * 64, 'graph_sha256': 'b' * 64}
    metadata = {'configuration': configuration, 'configuration_sha256': 'a' * 64,
        'schedules': [{'source_id': body, 'graph_sha256': 'b' * 64, 'edge_events': [
            {'source_id': body, 'target_id': 20, 'tick': 4, 'count': body}]}
                      for body in [10, 11]]}
    data = json.dumps(metadata).encode()
    model = SimpleNamespace(name='model.json', storage_key='owned', size=len(data),
                            sha256=hashlib.sha256(data).hexdigest())
    source = SimpleNamespace(configuration=configuration, manifest=manifest, files=[model])
    class Storage:
        async def download_file_stream(self, *, file_key, target, max_bytes):
            assert file_key == 'owned' and max_bytes == len(data)
            target.write(data)
            return len(data)
    result = await fragment_target_candidates(Storage(), source, 20)
    assert result['candidates'] == [
        {'source_id': 10, 'events': 10, 'first_tick_ms': 4, 'intervals_available': False},
        {'source_id': 11, 'events': 11, 'first_tick_ms': 4, 'intervals_available': False}]
    assert (await fragment_target_candidates(Storage(), source, 21))['candidates'] == []
    with pytest.raises(ValueError, match='configuration'):
        await fragment_target_candidates(Storage(), source, 10)
    model.sha256 = '0' * 64
    with pytest.raises(ValueError, match='checksum'):
        await fragment_target_candidates(Storage(), source, 20)


def test_interval_coverage_is_not_inferred_from_partial_metadata():
    from service.services.simulations.inputs.fragment_target_candidates import _has_crossing_intervals
    schedule = {'edge_events': [{'target_id': 20, 'tick': 4, 'count': 1}]}
    row = {'included_in_graph': True, 'partner_id': '20', 'stimulated_ticks_ms': [4],
           'stimulated_crossing_intervals': [{'lower_ms': 3.1, 'upper_ms': 3.15, 'tick_ms': 4}]}
    metadata = {'diagnostics': [{'body_id': '10', 'candidates': [row]}]}
    assert _has_crossing_intervals(metadata, 10, 20, schedule)
    row.pop('stimulated_crossing_intervals')
    assert not _has_crossing_intervals(metadata, 10, 20, schedule)
