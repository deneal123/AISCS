import hashlib
import threading

import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.population_recording import (
    PopulationRecording,
)


def cell(body):
    return {'id': body, 'geometry': {'starts_um': [[0., 0., 0.]],
            'ends_um': [[2., 0., 0.]], 'midpoints_um': [[1., 0., 0.]],
            'endpoint_radii_um': [[.1, .1]]}}


def accumulator():
    return PopulationRecording([1, 2], electrode_um=[10., 0., 0.],
        reference_um=[20., 0., 0.], conductivity_s_m=.3, clearance_um=1., samples=3)


def test_population_recording_sums_bounded_batches():
    target = accumulator()
    first = target.factory([cell(2)])
    assert first['selected_indices'] == {2: []}
    first['sink'](0, 1, [{'id': 2, 'neural_uv': [1.]}])
    with pytest.raises(ValueError, match='Incomplete'):
        target.finish()
    first['sink'](1, 3, [{'id': 2, 'neural_uv': [2., 3.]}])
    second = target.factory([cell(1)])
    second['sink'](0, 3, [{'id': 1, 'neural_uv': [4., 5., 6.]}])
    np.testing.assert_array_equal(target.finish(), [5., 7., 9.])
    with pytest.raises(ValueError, match='identities'):
        target.factory([cell(1)])


@pytest.mark.parametrize('rows', [[{'id': 2, 'neural_uv': [1.]}],
                                  [{'id': 1, 'neural_uv': [float('nan')]}]])
def test_bad_window_prevents_publication(rows):
    target = accumulator()
    batch = target.factory([cell(1)])
    with pytest.raises(ValueError):
        batch['sink'](0, 1, rows)
    with pytest.raises(ValueError, match='Incomplete'):
        target.finish()


def test_population_recording_streams_selected_voltages():
    captured = []
    target = PopulationRecording([1], electrode_um=[10., 0., 0.], reference_um=[20., 0., 0.],
        conductivity_s_m=.3, clearance_um=1., samples=3,
        selection_factory=lambda cells: {cells[0]['id']: [0]},
        selected_sink=lambda start, end, rows, selection: captured.append(
            (start, end, rows[0]['selected_voltage_mv'], selection)))
    batch = target.factory([cell(1)])
    assert batch['selected_indices'] == {1: [0]}
    batch['sink'](0, 3, [{'id': 1, 'neural_uv': [1., 2., 3.],
                           'selected_voltage_mv': [[-65., -20., -65.]]}])
    np.testing.assert_array_equal(target.finish(), [1., 2., 3.])
    assert captured == [(0, 3, [[-65., -20., -65.]], {1: [0]})]


def test_population_recording_rejects_unpaired_selection_sink():
    with pytest.raises(ValueError, match='identities or samples'):
        PopulationRecording([1], electrode_um=[10., 0., 0.], reference_um=[20., 0., 0.],
            conductivity_s_m=.3, clearance_um=1., samples=3,
            selection_factory=lambda cells: {1: [0]})


def test_population_recording_rejects_unexpected_or_repeated_batch_ids():
    target = accumulator()
    with pytest.raises(ValueError, match='identities'):
        target.factory([cell(3)])
    with pytest.raises(ValueError, match='identities'):
        target.factory([cell(1), cell(1)])
    batch = target.factory([cell(1)])
    batch['sink'](0, 3, [{'id': 1, 'neural_uv': [0., 0., 0.]}])
    with pytest.raises(ValueError, match='identities'):
        target.factory([cell(1), cell(2)])


def test_recording_pipeline_reads_verified_chunk_with_bounds(tmp_path, monkeypatch):
    from service.infrastructure.stimulation.experimental_gpu import batch_solver, population_replay
    from service.infrastructure.stimulation.experimental_gpu.fast_cable import CACHE_RECORD, Params

    rows = np.array([(0., 0., 0., .1, -1, 1), (2., 0., 0., .1, 0, 2),
                     (0., 2., 0., .1, -1, 1), (2., 2., 0., .1, 0, 2)],
                    dtype=CACHE_RECORD)
    raw = rows.tobytes()
    (tmp_path / 'chunk-000000.bin').write_bytes(raw)
    sources = {1: 'a' * 64, 2: 'b' * 64}
    descriptor = {'name': 'chunk-000000.bin', 'format': 'malecns-packed-geometry-chunk-v1',
        'vertices': 4, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
        'neurons': [{'body_id': str(body), 'source_sha256': sources[body],
                     'offset': i * 2, 'count': 2} for i, body in enumerate((1, 2))]}
    metadata = {'directory': tmp_path, 'neurons': 2, 'vertices': 4, 'chunks': [descriptor]}
    params = Params(source_um=(100., 100., 100.), return_um=(200., 100., 100.),
                    current_na=1., conductivity_s_m=.3, clearance_um=.1)
    recording = accumulator()
    monkeypatch.setattr(batch_solver, 'build_cell_major', lambda *a: ('packed',))

    def solve(group, stimulus, table, **options):
        assert options['cell_major'] and options['record_traces']
        assert all(cell['geometry']['endpoint_radii_um'].shape == (1, 2) for cell in group)
        options['device_window_sink'](0, 3,
            [{'id': item['id'], 'neural_uv': [float(item['id'])] * 3} for item in group])
        # The consumer refuses a batch whose receipt does not say which kernel
        # solved it, so a stand-in solver must report the accelerated path.
        return {'accelerated_cell_major': True}

    monkeypatch.setattr(batch_solver, 'solve_prepared_batch', solve)
    results = list(population_replay.solve_population(metadata, [0., 0., 0.], None,
        audited_sources=sources, params=params, segment_budget=10, output_budget_bytes=10000,
        workers=1, max_cells=1, pool_cells=1, window_cells=1,
        device_window_factory=recording.factory))
    assert sorted(body for ids, _ in results for body in ids) == [1, 2]
    np.testing.assert_array_equal(recording.finish(), [3., 3., 3.])

def test_population_recording_snapshots_cells_still_in_flight():
    # Window delivery runs on its own thread, so a batch's last window can still
    # be streaming when the solver hands its receipt back. The snapshot therefore
    # counts a cell as accounted for as soon as it is in flight, and must not
    # raise if the delivery thread retires the batch at the same moment.
    target = accumulator()
    batch = target.factory([cell(1)])
    assert target.settled() == {1}
    batch['sink'](0, 3, [{'id': 1, 'neural_uv': [1., 2., 3.]}])
    assert target.settled() == {1}
    with pytest.raises(ValueError, match='Incomplete'):
        target.finish()
    second = target.factory([cell(2)])
    second['sink'](0, 3, [{'id': 2, 'neural_uv': [1., 2., 3.]}])
    assert target.settled() == {1, 2}
    target.finish()


def test_population_recording_settled_survives_concurrent_delivery():
    # A regression guard for the crash this snapshot replaced: iterating the raw
    # in-flight table from the solver thread raced the delivery thread and raised
    # RuntimeError('dictionary changed size during iteration').
    target = accumulator()
    first = target.factory([cell(1)])
    observed = []

    def deliver():
        for end in (1, 2, 3):
            first['sink'](end - 1, end, [{'id': 1, 'neural_uv': [1.]}])
            observed.append(target.settled())

    worker = threading.Thread(target=deliver)
    worker.start()
    for _ in range(200):
        assert target.settled() == {1}
    worker.join()
    assert all(1 in snapshot for snapshot in observed)
    assert target.settled() == {1}
