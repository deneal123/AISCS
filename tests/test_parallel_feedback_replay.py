import hashlib
import io
import json
import multiprocessing as mp
import sys

import numpy as np
import pytest

pytest.importorskip('neuron')

from service.application.feedback.cell_cache import CellSolutionCache  # noqa: E402
from service.application.feedback.replay import replay_population_feedback  # noqa: E402
from service.domain.contracts.population.fragment import FragmentPopulationConfig  # noqa: E402
from service.infrastructure.connectome.morphology_repository import BASE  # noqa: E402
from tests.test_fragment_population_contract import example  # noqa: E402


@pytest.mark.skipif(sys.platform != 'linux', reason='parallel pool requires Linux')
def test_parallel_neuron_replay_preserves_every_output_and_cached_identity(tmp_path):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    hashes = {}
    for body, y in ((10, 1250), (20, 1500)):
        raw = (f'1 1 0 {y} 0 62.5 -1\n2 3 1250 {y} 0 62.5 1\n'
               f'3 3 2500 {y} 0 62.5 2\n').encode()
        hashes[body] = hashlib.sha256(raw).hexdigest()
        (tmp_path / 'raw' / f'{body}.swc').write_bytes(raw)
        (tmp_path / 'receipts' / f'{body}.json').write_text(json.dumps({
            'body_id': body, 'url': BASE + f'{body}.swc', 'sha256': hashes[body]}))
    config = FragmentPopulationConfig.model_validate(example())
    event = {'child_node_id': 2, 'position': .5, 'time_ms': 4., 'weight_us': .001,
             'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    schedule = {'graph_sha256': 'a' * 64, 'source_ids': [10, 20],
                'events_by_target': {10: [], 20: [event]},
                'target_morphology_sha256': {20: hashes[20]}, 'event_count': 1}
    serial_provenance, parallel_provenance = io.BytesIO(), io.BytesIO()
    serial_cells, parallel_cells = [], []
    progress = []

    def capture(target):
        return lambda body, solution, proof: target.append((body, solution, proof))

    serial = replay_population_feedback(config, [tmp_path], schedule, hashes, omitted_pairs=[],
        provenance_sink=serial_provenance, solution_sink=capture(serial_cells))
    cache = CellSolutionCache(10_000_000)
    parallel = replay_population_feedback(config, [tmp_path], schedule, hashes, omitted_pairs=[],
        provenance_sink=parallel_provenance, solution_sink=capture(parallel_cells),
        cell_cache=cache, experimental_cell_workers=2,
        cell_progress=lambda done, total: progress.append((done, total)))
    assert parallel['experimental_cell_workers'] == 2
    assert progress == [(1, 2), (2, 2)]
    assert [row[0] for row in parallel_cells] == [10, 20]
    assert parallel_provenance.getvalue() == serial_provenance.getvalue()
    for name in ('time_ms', 'neural_uv', 'stimulus_artifact_uv', 'total_uv'):
        np.testing.assert_array_equal(parallel['recording'][name], serial['recording'][name])
    for (_, original, proof), (_, result, other_proof) in zip(
            serial_cells, parallel_cells, strict=True):
        assert proof == other_proof
        assert original.keys() == result.keys()
        for name in original:
            np.testing.assert_array_equal(original[name], result[name])

    replayed = replay_population_feedback(config, [tmp_path], schedule, hashes, omitted_pairs=[],
        cell_cache=cache, experimental_cell_workers=2)
    np.testing.assert_array_equal(replayed['recording']['neural_uv'],
                                  serial['recording']['neural_uv'])

    existing_children = {child.pid for child in mp.active_children()}

    def reject_first(body, _solution, _proof):
        assert body == 10
        raise OSError('result storage failed')

    with pytest.raises(OSError, match='result storage failed'):
        replay_population_feedback(config, [tmp_path], schedule, hashes, omitted_pairs=[],
            solution_sink=reject_first, experimental_cell_workers=2)
    assert {child.pid for child in mp.active_children()} <= existing_children

    (tmp_path / 'raw' / '10.swc').write_text('changed')
    with pytest.raises(ValueError, match='failed validation'):
        replay_population_feedback(config, [tmp_path], schedule, hashes, omitted_pairs=[],
                                   cell_cache=cache, experimental_cell_workers=2)
