import hashlib
import json

import pytest

from scripts.compute_network_field import compute
from service.infrastructure.connectome.morphology_repository import BASE

CONFIG = dict(source_um=[0, 10, 0], return_um=[50, 10, 0], current_na=10,
              conductivity_s_m=.3, clearance_um=1)


def test_resume_preserves_order_and_detects_tampering(tmp_path):
    output = tmp_path / 'field.jsonl'
    assert compute([1, 2], [], output, CONFIG, graph_hash='graph') == 2
    original = output.read_bytes()
    lines = original.splitlines(keepends=True)
    assert json.loads(lines[-1])['kind'] == 'footer'
    output.write_bytes(b''.join(lines[:2]))
    assert compute([1, 2], [], output, CONFIG, graph_hash='graph') == 2
    assert output.read_bytes() == original
    assert compute([1, 2], [], output, CONFIG, graph_hash='graph') == 2
    rows = [json.loads(line) for line in lines]
    rows[1]['status'] = 'ok'
    output.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(ValueError, match='checksum'):
        compute([1, 2], [], output, CONFIG, graph_hash='graph')
    output.write_bytes(original[:-3])
    with pytest.raises(ValueError, match='incomplete'):
        compute([1, 2], [], output, CONFIG, graph_hash='graph')


def test_row_guard_fails_before_processing_the_remaining_population(tmp_path):
    seen = []

    def guard(row):
        seen.append(row['body_id'])
        if row['status'] == 'source_missing':
            raise ValueError('field_source_missing')

    output = tmp_path / 'guarded.jsonl'
    with pytest.raises(ValueError, match='field_source_missing'):
        compute([1, 2, 3], [], output, CONFIG, graph_hash='graph', check_row=guard)
    assert seen == ['1']
    assert len(output.read_text().splitlines()) == 1


def test_resume_rejects_changed_configuration_without_mutation(tmp_path):
    output = tmp_path / 'field.jsonl'
    compute([1], [], output, CONFIG, graph_hash='graph')
    original = output.read_bytes()
    with pytest.raises(ValueError, match='configuration'):
        compute([1], [], output, {**CONFIG, 'current_na': 20}, graph_hash='graph')
    assert output.read_bytes() == original


def test_resume_rejects_changed_pool_lifecycle_provenance(tmp_path, monkeypatch):
    from service.infrastructure.execution import pool_lifecycle

    output = tmp_path / 'field.jsonl'
    compute([1], [], output, CONFIG, graph_hash='graph')
    original = output.read_bytes()
    modified = tmp_path / 'other_pool_lifecycle.py'
    modified.write_text('different lifecycle implementation\n', encoding='utf8')
    monkeypatch.setattr(pool_lifecycle, '__file__', str(modified))
    with pytest.raises(ValueError, match='provenance or configuration'):
        compute([1], [], output, CONFIG, graph_hash='graph')
    assert output.read_bytes() == original


def test_parallel_results_match_serial_and_resume_across_worker_counts(tmp_path):
    source = tmp_path / 'source'
    (source / 'raw').mkdir(parents=True)
    (source / 'receipts').mkdir()
    swc = b'1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 3 375 0 0 1 2\n'
    for body in (1, 3, 35):
        (source / 'raw' / f'{body}.swc').write_bytes(swc)
        (source / 'receipts' / f'{body}.json').write_text(json.dumps({
            'body_id': body, 'url': BASE + f'{body}.swc',
            'sha256': hashlib.sha256(swc).hexdigest(),
        }))
    ids = list(range(1, 40))
    serial, parallel = tmp_path / 'serial.jsonl', tmp_path / 'parallel.jsonl'
    assert compute(ids, [source], serial, CONFIG, graph_hash='graph') == len(ids)
    assert compute(ids, [source], parallel, CONFIG, graph_hash='graph', workers=2) == len(ids)
    assert parallel.read_bytes() == serial.read_bytes()
    rows = [json.loads(line) for line in serial.read_text().splitlines()]
    assert rows[1]['status'] == 'ok'
    assert rows[2]['status'] == 'source_missing'
    # Simulate interruption after a complete line; switching worker count is safe.
    parallel.write_bytes(b''.join(serial.read_bytes().splitlines(keepends=True)[:19]))
    assert compute(ids, [source], parallel, CONFIG, graph_hash='graph', workers=2) == len(ids)
    assert parallel.read_bytes() == serial.read_bytes()


def test_real_gpu_parallel_preparation_matches_serial_and_resume(tmp_path):
    cuda = pytest.importorskip('numba.cuda')
    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    source = tmp_path / 'source'
    (source / 'raw').mkdir(parents=True)
    (source / 'receipts').mkdir()
    swc = b'1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 3 375 0 0 1 2\n'
    ids = list(range(1, 72))
    for body in ids:
        if body == 35:
            continue
        (source / 'raw' / f'{body}.swc').write_bytes(swc)
        (source / 'receipts' / f'{body}.json').write_text(json.dumps({
            'body_id': body, 'url': BASE + f'{body}.swc',
            'sha256': '0' * 64 if body == 36 else hashlib.sha256(swc).hexdigest(),
        }))
    serial, parallel = tmp_path / 'serial-gpu.jsonl', tmp_path / 'parallel-gpu.jsonl'
    assert compute(ids, [source], serial, CONFIG, graph_hash='graph',
                   field_backend='gpu') == len(ids)
    assert compute(ids, [source], parallel, CONFIG, graph_hash='graph', field_backend='gpu',
                   workers=2) == len(ids)
    assert parallel.read_bytes() == serial.read_bytes()
    rows = [json.loads(line) for line in serial.read_text().splitlines()]
    assert rows[35]['status'] == 'source_missing'
    assert rows[36]['status'] == 'invalid_geometry_or_field'
    parallel.write_bytes(b''.join(serial.read_bytes().splitlines(keepends=True)[:40]))
    assert compute(ids, [source], parallel, CONFIG, graph_hash='graph', field_backend='gpu',
                   workers=2) == len(ids)
    assert parallel.read_bytes() == serial.read_bytes()


@pytest.mark.parametrize('workers', [0, 9, True, 1.5])
def test_invalid_worker_count_does_not_create_output(tmp_path, workers):
    output = tmp_path / 'field.jsonl'
    with pytest.raises(ValueError, match='workers'):
        compute([1], [], output, CONFIG, graph_hash='graph', workers=workers)
    assert not output.exists()


def test_invalid_backend_does_not_create_output(tmp_path):
    output = tmp_path / 'field.jsonl'
    with pytest.raises(ValueError, match='Unknown field backend'):
        compute([1], [], output, CONFIG, graph_hash='graph', field_backend='unknown')
    assert not output.exists()


def test_fused_backend_requires_authenticated_cache_before_output(tmp_path):
    output = tmp_path / 'field.jsonl'
    with pytest.raises(ValueError, match='requires an authenticated geometry cache'):
        compute([1], [], output, CONFIG, graph_hash='graph', field_backend='gpu-fused')
    assert not output.exists()


def test_unavailable_gpu_does_not_fall_back_or_create_output(tmp_path, monkeypatch):
    def unavailable():
        raise RuntimeError('CUDA field backend is unavailable')

    monkeypatch.setattr('service.infrastructure.stimulation.point_field_gpu._kernel', unavailable)
    output = tmp_path / 'field.jsonl'
    with pytest.raises(RuntimeError, match='CUDA field backend is unavailable'):
        compute([1], [], output, CONFIG, graph_hash='graph', field_backend='gpu')
    assert not output.exists()


@pytest.mark.parametrize('rows, error', [
    ([{'body_id': '2', 'status': 'source_missing'}], 'do not match'),
    ([{'body_id': '1', 'status': 'source_missing'}], 'ended before'),
    ([{'body_id': '1', 'status': 'source_missing'},
      {'body_id': '2', 'status': 'source_missing'},
      {'body_id': '3', 'status': 'source_missing'}], 'do not match'),
])
def test_generated_rows_are_checked_before_completion(tmp_path, monkeypatch, rows, error):
    from service.infrastructure.stimulation.field import summary_compute as field_summary_compute

    monkeypatch.setattr(field_summary_compute, '_field_rows', lambda *args: iter(rows))
    output = tmp_path / 'field.jsonl'
    with pytest.raises(ValueError, match=error):
        compute([1, 2], [], output, CONFIG, graph_hash='graph')
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert all(row.get('kind') != 'footer' for row in records)


def test_field_progress_reports_completed_small_and_resumed_runs(tmp_path):
    output = tmp_path / 'field.jsonl'
    updates = []
    compute([1, 2], [], output, CONFIG, graph_hash='graph',
            progress=lambda done, total: updates.append((done, total)))
    assert updates == [(2, 2)]
    output.write_bytes(b''.join(output.read_bytes().splitlines(keepends=True)[:2]))
    updates.clear()
    compute([1, 2], [], output, CONFIG, graph_hash='graph',
            progress=lambda done, total: updates.append((done, total)))
    assert updates == [(2, 2)]
