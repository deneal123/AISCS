import hashlib
import json

import pytest

from service.services.simulations.manifests.full_feedback_manifest import (
    InvalidFullFeedbackManifest,
    validate_full_feedback_manifest,
    validate_full_feedback_preview,
)


def result():
    config = {'graph_sha256': 'a' * 64, 'max_iterations': 5,
              'simulation': {'duration_ms': 10, 'dt_ms': 1}}
    raw = json.dumps(config, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(raw).hexdigest()
    names = ('initial-active.jsonl', 'control.jsonl', 'activity.jsonl', 'signals.npz',
             'preview.json', 'coupled-source-events.bin')
    manifest = {'kind': 'experimental-full-population-feedback', 'status': 'converged',
        'graph_sha256': 'a' * 64, 'configuration_sha256': digest, 'configuration': config,
        'cells': 2, 'iterations': 2, 'control_iterations': 1,
        'control_feedback_schedule_sha256': 'c' * 64,
        'file_hashes': {name: 'b' * 64 for name in names},
        'files': [{'name': name, 'bytes': 100, 'sha256': 'b' * 64} for name in names]}
    preview = {'kind': manifest['kind'], 'status': 'converged', 'graph_cells': 2,
        'source_cells': 2, 'duration_ms': 10, 'iterations': 2, 'control_iterations': 1,
        'candidate_cell_time_markers': 3,
        'timeline': {'samples': 11, 'shown_samples': 2, 'time_ms': [0., 10.],
            'neural_uv': [0., 1.], 'control_uv': [0., 0.], 'stimulus_fraction': [0., 0.],
            'units': {'time_ms': 'ms', 'neural_uv': 'µV', 'control_uv': 'µV'}}}
    return manifest, preview, digest


def test_full_feedback_requires_matching_identity_and_complete_artifacts():
    manifest, preview, digest = result()
    validate_full_feedback_manifest(manifest, configuration_sha256=digest,
                                    graph_sha256='a' * 64, graph_cells=2)
    validate_full_feedback_preview(preview, manifest=manifest)
    with pytest.raises(InvalidFullFeedbackManifest):
        validate_full_feedback_manifest({**manifest, 'cells': 1}, configuration_sha256=digest,
                                        graph_sha256='a' * 64, graph_cells=2)
    with pytest.raises(InvalidFullFeedbackManifest):
        validate_full_feedback_manifest(manifest, configuration_sha256=digest,
            graph_sha256='a' * 64, graph_cells=2, request_sha256='f' * 64)
    with pytest.raises(InvalidFullFeedbackManifest):
        validate_full_feedback_manifest({**manifest, 'files': manifest['files'][:-1]},
            configuration_sha256=digest, graph_sha256='a' * 64, graph_cells=2)
    with pytest.raises(InvalidFullFeedbackManifest):
        validate_full_feedback_preview({**preview, 'candidate_cell_time_markers': 21},
                                       manifest=manifest)
    with pytest.raises(InvalidFullFeedbackManifest):
        validate_full_feedback_preview(preview, manifest={**manifest, 'configuration': []})


def test_full_feedback_rejects_changed_configuration_and_file_digest():
    manifest, _, digest = result()
    with pytest.raises(InvalidFullFeedbackManifest):
        validate_full_feedback_manifest({**manifest, 'configuration': {
            **manifest['configuration'], 'max_iterations': 7}},
            configuration_sha256=digest, graph_sha256='a' * 64, graph_cells=2)
    changed = [{**item} for item in manifest['files']]
    changed[0]['sha256'] = 'c' * 64
    with pytest.raises(InvalidFullFeedbackManifest):
        validate_full_feedback_manifest({**manifest, 'files': changed},
            configuration_sha256=digest, graph_sha256='a' * 64, graph_cells=2)


def test_numerical_parameters_must_match_the_operator_request():
    manifest, _, _ = result()
    request = {'simulation': {'duration_ms': 10}, 'threshold_mv': -20.,
        'max_source_distance_um': 2., 'max_target_distance_um': 2., 'max_iterations': 5,
        'max_events': 100, 'excitatory': {'weight_us': 1.}, 'inhibitory': {'weight_us': 2.},
        'allow_known_geometry_repair': False}
    request_hash = 'f' * 64
    numerical = {'graph_sha256': 'a' * 64, **{key: request[key] for key in (
        'simulation', 'threshold_mv', 'max_source_distance_um', 'max_target_distance_um',
        'max_iterations', 'max_events')}, 'synapse_parameters': {
            '1': request['excitatory'], '-1': request['inhibitory']},
        'geometry_repair': None, 'request_sha256': request_hash}
    raw = json.dumps(numerical, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(raw).hexdigest()
    manifest.update(configuration=numerical, configuration_sha256=digest)
    validate_full_feedback_manifest(manifest, configuration_sha256=digest, graph_sha256='a' * 64,
        graph_cells=2, request_sha256=request_hash, request_configuration=request)
    with pytest.raises(InvalidFullFeedbackManifest, match='full_feedback_request'):
        validate_full_feedback_manifest(manifest, configuration_sha256=digest,
            graph_sha256='a' * 64, graph_cells=2, request_sha256=request_hash,
            request_configuration={**request, 'threshold_mv': -10.})


def test_unresolved_source_is_a_safe_geometry_failure():
    from service.services.simulations.failure_codes import executor_failure_code

    assert executor_failure_code({'status': 'failed', 'error': {'type': 'ValueError',
        'message': 'Unresolved source geometry prevents complete feedback'}}) == (
            'executor_synapse_geometry')
    assert executor_failure_code({'status': 'failed', 'error': {'type': 'ValueError',
        'message': 'Unresolved feedback endpoint in target cell 10456'}}) == (
            'executor_synapse_endpoint')
