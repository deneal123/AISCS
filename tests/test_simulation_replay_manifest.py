from uuid import UUID

import pytest

from service.services.simulations.manifests.replay_manifest import (
    InvalidReplayManifest,
    validate_replay_manifest,
    validate_replay_preview,
)

SOURCE = UUID('00000000-0000-4000-8000-000000000001')
DIGEST = 'a' * 64


def manifest():
    return {'format': 'independent-swc-replay-artifact-v1', 'kind': 'independent-cell-replay',
            'configuration_sha256': DIGEST, 'source_run_id': str(SOURCE),
            'units': {'time_ms': 'ms', 'neural_uv': 'µV', 'stimulus_artifact_uv': 'µV',
                      'total_uv': 'µV'},
            'files': [{'name': 'replay-evidence.json', 'bytes': 1, 'sha256': 'b' * 64},
                      {'name': 'replay-signal.npz', 'bytes': 2, 'sha256': 'c' * 64},
                      {'name': 'replay-preview.json', 'bytes': 3, 'sha256': 'd' * 64}]}


def test_valid_replay_manifest():
    validate_replay_manifest(manifest(), configuration_sha256=DIGEST, source_run_id=SOURCE)


@pytest.mark.parametrize(
    'mutate', ['source', 'config', 'units', 'duplicate', 'path', 'size', 'hash', 'preview_size']
)
def test_rejects_mismatched_replay_artifact(mutate):
    data = manifest()
    if mutate == 'source':
        data['source_run_id'] = str(UUID(int=2))
    elif mutate == 'config':
        data['configuration_sha256'] = 'f' * 64
    elif mutate == 'units':
        data['units']['neural_uv'] = 'mV'
    elif mutate == 'duplicate':
        data['files'][1]['name'] = data['files'][0]['name']
    elif mutate == 'path':
        data['files'][0]['name'] = '../replay-evidence.json'
    elif mutate == 'size':
        data['files'][0]['bytes'] = True
    elif mutate == 'preview_size':
        data['files'][2]['bytes'] = 1024 * 1024 + 1
    else:
        data['files'][0]['sha256'] = 'x' * 64
    with pytest.raises(InvalidReplayManifest):
        validate_replay_manifest(data, configuration_sha256=DIGEST, source_run_id=SOURCE)


def preview():
    return {'time_ms': [0., 1., 2.], 'signal_uv': [0., 1., 0.],
            'original_samples': 3, 'shown_samples': 3, 'body_id': '42',
            'units': {'time_ms': 'ms', 'signal_uv': 'µV'},
            'signal_scope': 'neural contribution of one independently replayed SWC cell',
            'complete_graph_edge_coverage': True, 'limitations': ['one-way replay']}


def test_preview_must_identify_valid_sample_grid_and_target():
    config = {'body_id': 42, 'simulation': {'duration_ms': 2., 'dt_ms': 1.}}
    validate_replay_preview(preview(), config)
    for field, value in [('body_id', '43'), ('time_ms', [0., 2., 1.]),
                         ('signal_uv', [0., float('nan'), 0.]), ('shown_samples', True),
                         ('units', {'time_ms': 's', 'signal_uv': 'µV'}),
                         ('signal_scope', 'full CNS')]:
        data = preview()
        data[field] = value
        with pytest.raises(InvalidReplayManifest):
            validate_replay_preview(data, config)
