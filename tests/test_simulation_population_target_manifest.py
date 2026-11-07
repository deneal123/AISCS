import copy

import pytest

from service.services.simulations.manifests.population_target_manifest import (
    InvalidPopulationTargetManifest,
    validate_population_target_manifest,
    validate_population_target_preview,
)


def preview():
    return {'samples': 3, 'shown_samples': 3, 'time_ms': [0., 1., 2.],
            'source_neural_uv': [1., 1., 1.], 'target_neural_uv': [2., 2., 2.],
            'target_delta_uv': [0., 1., 0.], 'neural_uv': [3., 3., 3.],
            'stimulus_artifact_uv': [0., 4., 0.], 'total_uv': [3., 7., 3.],
            'source_cells': 2, 'target_cells': 1, 'target_id': 20,
            'selected_source_ids': [10, 11], 'events': 5,
            'units': {'time_ms': 'ms', 'signal': 'µV'},
            'limitations': ['Односторонний повтор без обратной связи с сетью.',
                            'Физическая запись ограничена указанными клетками.',
                            'Параметры синапсов и тканей не откалиброваны.']}


def test_target_preview_checks_scope_times_and_signal_equations():
    config = {'duration_ms': 2, 'target_id': 20, 'source_ids': [10, 11], 'max_events': 10}
    source = {'simulation': {'dt_ms': 1.}, 'source_ids': [10, 11]}
    validate_population_target_preview(preview(), config, source)
    for key, value in [('source_cells', 3), ('target_id', 21), ('events', 11),
                       ('time_ms', [0, 1, 1]), ('time_ms', [0, 1.1, 2]),
                       ('total_uv', [3, 8, 3])]:
        wrong = copy.deepcopy(preview())
        wrong[key] = value
        with pytest.raises(InvalidPopulationTargetManifest):
            validate_population_target_preview(wrong, config, source)


def test_preview_accepts_small_solver_roundoff_but_not_off_grid_samples():
    config = {'duration_ms': 2, 'target_id': 20, 'source_ids': [10, 11], 'max_events': 10}
    source = {'simulation': {'dt_ms': .1}, 'source_ids': [10, 11]}
    rounded = preview()
    rounded['samples'] = 21
    rounded['time_ms'] = [0., 1.00000000001, 2.00000000001]
    validate_population_target_preview(rounded, config, source)
    rounded['time_ms'][1] = 1.001
    with pytest.raises(InvalidPopulationTargetManifest):
        validate_population_target_preview(rounded, config, source)


def test_target_voltage_preview_requires_explicit_compartment_and_both_traces():
    config = {'duration_ms': 2, 'target_id': 20, 'source_ids': [10, 11], 'max_events': 10}
    source = {'simulation': {'dt_ms': 1.}, 'source_ids': [10, 11]}
    data = preview()
    data.update({'voltage_probe': {'child_node_id': 9, 'segment_index': 0, 'segments_per_edge': 1,
        'segment_center': .5,
        'interpretation': 'first matched event compartment; uncalibrated model voltage'},
        'probe_baseline_mv': [-65., -64., -65.], 'probe_active_mv': [-65., -20., -65.]})
    validate_population_target_preview(data, config, source)
    data['probe_morphology_sha256'] = 'c' * 64
    validate_population_target_preview(data, config, source)
    data['probe_morphology_sha256'] = 'broken'
    with pytest.raises(InvalidPopulationTargetManifest):
        validate_population_target_preview(data, config, source)
    data['probe_morphology_sha256'] = 'c' * 64
    data['voltage_probe']['segment_index'] = 2
    with pytest.raises(InvalidPopulationTargetManifest):
        validate_population_target_preview(data, config, source)


def test_target_timing_mode_is_bound_to_configuration():
    config = {'duration_ms': 2, 'target_id': 20, 'source_ids': [10, 11], 'max_events': 10}
    source = {'simulation': {'dt_ms': 1.}, 'source_ids': [10, 11]}
    data = preview()
    data['timing_mode'] = 'upper_bound'
    with pytest.raises(InvalidPopulationTargetManifest):
        validate_population_target_preview(data, config, source)
    validate_population_target_preview(data, {**config, 'timing_mode': 'upper_bound'}, source)


def test_target_manifest_requires_exact_artifacts_and_digest():
    names = ['target-model.json', 'target-signals.npz', 'target-preview.json']
    manifest = {'kind': 'experimental-one-way-target-replay', 'configuration_sha256': 'a' * 64,
                'files': [{'name': name, 'bytes': 10, 'sha256': 'b' * 64} for name in names]}
    validate_population_target_manifest(manifest, configuration_sha256='a' * 64)
    manifest['files'][0]['name'] = '../model.json'
    with pytest.raises(InvalidPopulationTargetManifest):
        validate_population_target_manifest(manifest, configuration_sha256='a' * 64)
