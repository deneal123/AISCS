from copy import deepcopy

import pytest

from service.services.simulations.manifests.independent_population import (
    validate_independent_manifest,
    validate_independent_preview,
)


def test_manifest_rejects_ambiguous_or_missing_artifacts():
    manifest = {'format': 'independent-gpu-recording-v1',
        'kind': 'experimental-independent-population', 'configuration_sha256': 'a' * 64,
        'geometry_cache_manifest_sha256': 'b' * 64, 'source_index_sha256': 'c' * 64,
        'geometry_repair_policy': 'disabled', 'interpretation': 'no network feedback',
        'files': [{'name': name, 'bytes': 123, 'sha256': 'd' * 64}
                  for name in ('recording.npz', 'preview.json')]}
    validate_independent_manifest(manifest, configuration_sha256='a' * 64)
    invalid = deepcopy(manifest)
    invalid['files'][1]['name'] = 'recording.npz'
    with pytest.raises(ValueError):
        validate_independent_manifest(invalid, configuration_sha256='a' * 64)
    invalid = deepcopy(manifest)
    invalid['interpretation'] = 'complete network'
    with pytest.raises(ValueError):
        validate_independent_manifest(invalid, configuration_sha256='a' * 64)


def test_preview_rejects_nonfinite_and_wrong_duration():
    preview = {'kind': 'experimental-independent-population', 'cells': 166700,
        'samples': 3, 'shown_samples': 3, 'replacement_count': 1,
        'interpretation': 'no network feedback', 'units': {'time_ms': 'ms', 'neural_uv': 'µV'},
        'time_ms': [0., .05, .1], 'neural_uv': [0., 1., -1.]}
    config = {'simulation': {'duration_ms': .1}}
    validate_independent_preview(preview, config)
    with pytest.raises(ValueError):
        validate_independent_preview({**preview, 'neural_uv': [0., float('nan'), 1.]}, config)
    with pytest.raises(ValueError):
        validate_independent_preview(preview, {'simulation': {'duration_ms': .2}})
    validate_independent_preview(preview, {'simulation': {'duration_ms': .1, 'dt_ms': .05}})
    with pytest.raises(ValueError, match='grid'):
        validate_independent_preview({**preview, 'time_ms': [0., .04, .1]},
                                     {'simulation': {'duration_ms': .1, 'dt_ms': .05}})
    with pytest.raises(ValueError, match='grid'):
        validate_independent_preview({**preview, 'samples': 4},
                                     {'simulation': {'duration_ms': .1, 'dt_ms': .05}})
