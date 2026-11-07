import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.morphology_field import evaluate_registered_neuron_field
from service.infrastructure.stimulation.network_field import registered_field_summaries


def test_summaries_preserve_every_registered_id_and_source_identity(tmp_path):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    raw = b'1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 3 375 0 0 1 2\n'
    (tmp_path / 'raw' / '1.swc').write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / 'receipts' / '1.json').write_text(json.dumps({
        'body_id': 1, 'url': BASE + '1.swc', 'sha256': digest,
    }))
    graph = SimpleNamespace(ids=np.array([1, 2]))
    options = dict(source_um=[0, 10, 0], return_um=[50, 10, 0], current_na=10,
                   conductivity_s_m=.3, clearance_um=1)
    iterator = registered_field_summaries(graph, [tmp_path], **options)
    assert iter(iterator) is iterator
    rows = list(iterator)
    expected = evaluate_registered_neuron_field(1, [tmp_path], **options)
    assert len(rows) == 2 and rows[0]['status'] == 'ok'
    assert rows[0]['source_sha256'] == digest and rows[0]['interpretation'] == 'field-only'
    assert rows[0]['max_abs_curvature_signed_mv_per_um2'] == pytest.approx(
        expected['curvature_mv_per_um2'][0])
    assert rows[1] == {'body_id': '2', 'status': 'source_missing'}
    (tmp_path / 'raw' / '1.swc').write_bytes(b'corrupt')
    corrupted = list(registered_field_summaries(graph, [tmp_path], **options))
    assert corrupted[0]['status'] == 'invalid_geometry_or_field'


def test_global_invalid_field_fails_before_any_per_neuron_result():
    graph = SimpleNamespace(ids=np.array([1]))
    with pytest.raises(ValueError, match='Conductivity'):
        list(registered_field_summaries(graph, [], [0, 0, 0], [20, 0, 0], 1, 0,
                                        clearance_um=1))


def test_grouped_field_isolates_invalid_neuron_and_keeps_valid_neighbors(tmp_path, monkeypatch):
    from service.infrastructure.stimulation.point_field import bipolar_potential_mv

    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    for body, y in [(1, 1250), (2, 0), (3, 2500)]:
        raw = (f'1 1 0 {y} 0 1 -1\n2 3 125 {y} 0 1 1\n'
               f'3 3 375 {y} 0 1 2\n').encode()
        (tmp_path / 'raw' / f'{body}.swc').write_bytes(raw)
        (tmp_path / 'receipts' / f'{body}.json').write_text(json.dumps({
            'body_id': body, 'url': BASE + f'{body}.swc',
            'sha256': hashlib.sha256(raw).hexdigest(),
        }))

    def grouped(groups, *args, **kwargs):
        points = np.concatenate(groups)
        values = bipolar_potential_mv(points, *args, clearance_um=kwargs['clearance_um'])
        return np.split(values, np.cumsum([len(group) for group in groups])[:-1])

    monkeypatch.setattr(
        'service.infrastructure.stimulation.point_field_gpu.bipolar_potential_groups_gpu', grouped)
    graph = SimpleNamespace(ids=np.array([1, 2, 3, 4]))
    options = dict(source_um=[0, 0, 0], return_um=[50, 0, 0], current_na=10,
                   conductivity_s_m=.3, clearance_um=1)
    cpu = list(registered_field_summaries(graph, [tmp_path], **options))
    batched = list(registered_field_summaries(graph, [tmp_path], **options, field_backend='gpu'))
    parallel = list(registered_field_summaries(graph, [tmp_path], **options, field_backend='gpu',
                                               field_workers=2))
    assert parallel == batched
    assert [row['status'] for row in batched] == [
        'ok', 'invalid_geometry_or_field', 'ok', 'source_missing']
    assert [row['body_id'] for row in batched] == ['1', '2', '3', '4']
    for i in [0, 2]:
        assert batched[i] == cpu[i]
