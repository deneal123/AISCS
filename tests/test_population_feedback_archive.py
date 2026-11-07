import hashlib
import json
import zipfile
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
from service.infrastructure.stimulation.population_feedback_archive import (
    read_population_feedback,
    write_population_feedback,
)
from tests.test_population_feedback_validation import example_result


def test_archive_round_trip_and_provenance(tmp_path, monkeypatch):
    result, graph, source = example_result()
    result['schedule']['provenance_by_target'] = {10: [], 20: []}
    monkeypatch.setattr('service.infrastructure.stimulation.population_feedback_archive.'
                        'load_verified_fragment_population', lambda *_: source)
    path = tmp_path / 'result.zip'
    args = {'source_directory': tmp_path, 'graph': graph,
            'parameters': {1: {'weight_us': .001}}, 'allow_partial_geometry': False}
    digest = write_population_feedback(result, path, **args)
    assert len(digest) == 64
    restored = read_population_feedback(path, **args)
    np.testing.assert_array_equal(restored['network']['spike_neurons'], [2])
    np.testing.assert_array_equal(restored['recording']['neural_uv'],
                                  result['recording']['neural_uv'])
    assert restored['physical_source_output'] == result['physical_source_output']
    assert restored['schedule'] == result['schedule']
    with pytest.raises(FileExistsError):
        write_population_feedback(result, path, **args)
    with pytest.raises(ValueError, match='provenance'):
        read_population_feedback(path, **{**args, 'parameters': {1: {'weight_us': .002}}})


def test_partial_source_geometry_survives_coupled_archive_round_trip(tmp_path, monkeypatch):
    result, graph, source = example_result()
    source['metadata']['configuration']['allow_partial_geometry'] = True
    config = FragmentPopulationConfig.model_validate(source['metadata']['configuration'])
    source['manifest']['configuration_sha256'] = config.digest()
    source['metadata']['diagnostics'][0]['candidates'][0]['centerline_distance_um'] = .1
    source['metadata']['diagnostics'][1]['candidates'][0]['centerline_distance_um'] = 2.1
    source['metadata']['schedules'] = [{'unresolved_geometry': []},
                                       {'unresolved_geometry': [{'candidate_index': 0}]}]
    physical = result['physical_source_output']
    physical['source_configuration_sha256'] = config.digest()
    physical['source_unresolved_graph_pairs'] = 1
    physical['candidate_events_by_source'][20] = []
    result['status'] = 'converged_partial'
    result['schedule']['provenance_by_target'] = {10: [], 20: []}
    monkeypatch.setattr('service.infrastructure.stimulation.population_feedback_archive.'
                        'load_verified_fragment_population', lambda *_: source)
    path = tmp_path / 'partial.zip'
    args = {'source_directory': tmp_path, 'graph': graph,
            'parameters': {1: {'weight_us': .001}}, 'allow_partial_geometry': True}
    write_population_feedback(result, path, **args)
    restored = read_population_feedback(path, **args)
    assert restored['status'] == 'converged_partial'
    assert restored['physical_source_output']['source_unresolved_graph_pairs'] == 1
    assert restored['physical_source_output']['candidate_events_by_source'][20] == []


def test_archive_rejects_tampered_payload(tmp_path, monkeypatch):
    result, graph, source = example_result()
    monkeypatch.setattr('service.infrastructure.stimulation.population_feedback_archive.'
                        'load_verified_fragment_population', lambda *_: source)
    path = tmp_path / 'result.zip'
    args = {'source_directory': tmp_path, 'graph': graph,
            'parameters': {1: {'weight_us': .001}}, 'allow_partial_geometry': False}
    write_population_feedback(result, path, **args)
    with zipfile.ZipFile(path) as archive:
        payload = {name: archive.read(name) for name in archive.namelist()}
    payload['model.json'] += b' '
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in payload.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match='checksum'):
        read_population_feedback(path, **args)


def test_legacy_archive_cannot_silently_ignore_refinement_fields(tmp_path, monkeypatch):
    result, graph, source = example_result()
    monkeypatch.setattr('service.infrastructure.stimulation.population_feedback_archive.'
                        'load_verified_fragment_population', lambda *_: source)
    path = tmp_path / 'result.zip'
    args = {'source_directory': tmp_path, 'graph': graph,
            'parameters': {1: {'weight_us': .001}}, 'allow_partial_geometry': False}
    write_population_feedback(result, path, **args)
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(contents['model.json'])
    metadata['discretization_receipt'] = {'targets': {}}
    contents['model.json'] = json.dumps(metadata).encode()
    manifest = json.loads(contents['manifest.json'])
    manifest['files'][0]['sha256'] = hashlib.sha256(contents['model.json']).hexdigest()
    manifest['files'][0]['bytes'] = len(contents['model.json'])
    contents['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match='provenance mismatch'):
        read_population_feedback(path, **args)


def test_writer_rejects_uncompressed_arrays_above_limit(tmp_path, monkeypatch):
    result, graph, source = example_result()
    module = 'service.infrastructure.stimulation.population_feedback_archive.'
    monkeypatch.setattr(module + 'load_verified_fragment_population', lambda *_: source)
    monkeypatch.setattr(module + 'MAX_BYTES', 1024)
    path = tmp_path / 'result.zip'
    with pytest.raises(ValueError, match='arrays exceed'):
        write_population_feedback(result, path, source_directory=tmp_path, graph=graph,
                                  parameters={1: {'weight_us': .001}},
                                  allow_partial_geometry=False)
    assert not path.exists()


def test_refined_archive_requires_explicit_context_and_revalidates_on_read(tmp_path, monkeypatch):
    result, graph, source = example_result()
    result['schedule']['provenance_by_target'] = {10: [], 20: []}
    graph.provenance['array_sha256'] = {'ids.npy': 'b' * 64}
    result['network']['metadata']['graph'] = graph.provenance
    result['discretization_receipts'] = [{'targets': {10: {'checked': True}}}]
    index = SimpleNamespace(manifest={'ids_sha256': 'b' * 64, 'source_md5': 'c' * 32})
    context = {'index': index, 'directories': [], 'policy': {'expected_source_md5': 'c' * 32}}
    module = 'service.infrastructure.stimulation.population_feedback_archive.'
    monkeypatch.setattr(module + 'load_verified_fragment_population', lambda *_: source)
    checked = []
    def verify(schedule, receipt, actual_index, directories, *, policy):
        assert schedule == result['schedule'] and actual_index is index and directories == []
        assert policy == context['policy']
        if receipt != {'targets': {10: {'checked': True}}}:
            raise ValueError('Modified receipt')
        checked.append(deepcopy(receipt))
        return receipt
    monkeypatch.setattr('service.application.feedback.population_feedback_validation.'
                        'verify_feedback_discretization', verify)
    args = {'source_directory': tmp_path, 'graph': graph,
            'parameters': {1: {'weight_us': .001}}, 'allow_partial_geometry': False}
    path = tmp_path / 'refined.zip'
    with pytest.raises(ValueError, match='without verified context'):
        write_population_feedback(result, path, **args)
    write_population_feedback(result, path, **args, discretization_context=context)
    with pytest.raises(ValueError, match='provenance mismatch'):
        read_population_feedback(path, **args)
    restored = read_population_feedback(path, **args, discretization_context=context)
    assert restored['discretization_receipt'] == result['discretization_receipts'][-1]
    assert len(checked) == 2
    bad = {**context, 'index': SimpleNamespace(manifest={**index.manifest, 'ids_sha256': 'd' * 64})}
    with pytest.raises(ValueError, match='index and graph identity mismatch'):
        read_population_feedback(path, **args, discretization_context=bad)
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(contents['model.json'])
    metadata['discretization_receipt']['targets']['10']['checked'] = False
    contents['model.json'] = json.dumps(metadata, sort_keys=True, separators=(',', ':'),
                                        ensure_ascii=False, allow_nan=False).encode()
    manifest = json.loads(contents['manifest.json'])
    manifest['files'][0]['sha256'] = hashlib.sha256(contents['model.json']).hexdigest()
    manifest['files'][0]['bytes'] = len(contents['model.json'])
    contents['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match='Modified receipt'):
        read_population_feedback(path, **args, discretization_context=context)
