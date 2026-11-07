import copy

import pytest

from service.services.simulations.manifests.field_proxy_manifest import (
    InvalidFieldProxyManifest,
    validate_field_proxy_manifest,
    validate_field_proxy_preview,
)


def manifest():
    return {'format': 'field-proxy-manifest-v1', 'kind': 'experimental-field-proxy',
            'configuration_sha256': 'a' * 64, 'files': [
                {'name': name, 'bytes': 12, 'sha256': 'b' * 64}
                for name in ('metadata.json', 'network.npz', 'network-events.bin', 'network-control-events.bin',
                             'state-response.bin', 'field-proxy-preview.json')]}


def test_validates_required_and_optional_artifacts():
    data = manifest()
    validate_field_proxy_manifest(data, configuration_sha256='a' * 64)
    data['files'].append({'name': 'state-delta.bin', 'bytes': 2, 'sha256': 'c' * 64})
    validate_field_proxy_manifest(data, configuration_sha256='a' * 64)


def test_preview_rejects_invented_recording_and_inconsistent_events():
    preview = {'kind': 'experimental-field-proxy', 'duration_ms': 2, 'time_step_ms': 1.0,
               'neurons': 3, 'spike_count': 2, 'active_neurons': 1,
               'spikes_by_ms': [0, 1, 1], 'control_spikes_by_ms': [0, 0, 1], 'direct_field_exclusions': 0,
               'contact_exclusions': 0, 'recording': None}
    validate_field_proxy_preview(preview, {'waveform': [0, 1]})
    for key, value in [('recording', [0, 1]), ('spike_count', 3), ('spikes_by_ms', [1, 1, 0])]:
        with pytest.raises(InvalidFieldProxyManifest):
            validate_field_proxy_preview({**preview, key: value}, {'waveform': [0, 1]})


@pytest.mark.parametrize('mutation', ['wrong_configuration', 'missing', 'duplicate', 'path', 'size', 'digest'])
def test_rejects_invalid_artifacts(mutation):
    data = copy.deepcopy(manifest())
    if mutation == 'wrong_configuration':
        data['configuration_sha256'] = 'c' * 64
    elif mutation == 'missing':
        data['files'].pop()
    elif mutation == 'duplicate':
        data['files'][1] = data['files'][0]
    elif mutation == 'path':
        data['files'][0]['name'] = '../metadata.json'
    elif mutation == 'size':
        data['files'][0]['bytes'] = True
    else:
        data['files'][0]['sha256'] = 'bad'
    with pytest.raises(InvalidFieldProxyManifest):
        validate_field_proxy_manifest(data, configuration_sha256='a' * 64)
