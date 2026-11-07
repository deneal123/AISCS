"""Validate bounded artifacts from the experimental field-proxy calculation."""

import re


class InvalidFieldProxyManifest(ValueError):
    pass


def validate_field_proxy_manifest(manifest, *, configuration_sha256):
    if (not isinstance(manifest, dict) or manifest.get('format') != 'field-proxy-manifest-v1'
            or manifest.get('kind') != 'experimental-field-proxy'
            or not isinstance(configuration_sha256, str)
            or not re.fullmatch(r'[a-f0-9]{64}', configuration_sha256)
            or manifest.get('configuration_sha256') != configuration_sha256):
        raise InvalidFieldProxyManifest('field_proxy_identity')
    required = {'metadata.json', 'network.npz', 'network-events.bin', 'network-control-events.bin',
                'state-response.bin', 'field-proxy-preview.json'}
    permitted = required | {'state-delta.bin'}
    files = manifest.get('files')
    if not isinstance(files, list) or not len(required) <= len(files) <= len(permitted):
        raise InvalidFieldProxyManifest('field_proxy_files')
    seen = set()
    for item in files:
        if not isinstance(item, dict):
            raise InvalidFieldProxyManifest('field_proxy_files')
        name, size, sha = item.get('name'), item.get('bytes'), item.get('sha256')
        if (not isinstance(name, str) or name not in permitted or name in seen
                or type(size) is not int
                or not 1 <= size <= 256 * 1024 * 1024
                or (name == 'metadata.json' and size > 8 * 1024 * 1024)
                or not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{64}', sha)):
            raise InvalidFieldProxyManifest('field_proxy_files')
        seen.add(name)
    if not required <= seen:
        raise InvalidFieldProxyManifest('field_proxy_files')


def validate_field_proxy_preview(preview, configuration):
    """Reject invented recordings and inconsistent model-event summaries."""
    if not isinstance(preview, dict) or not isinstance(configuration, dict):
        raise InvalidFieldProxyManifest('field_proxy_preview')
    waveform = configuration.get('waveform')
    duration = preview.get('duration_ms')
    neurons = preview.get('neurons')
    events = preview.get('spikes_by_ms')
    control = preview.get('control_spikes_by_ms')
    exclusions = (preview.get('direct_field_exclusions'), preview.get('contact_exclusions'))
    if (preview.get('kind') != 'experimental-field-proxy'
            or not isinstance(waveform, list) or type(duration) is not int
            or duration != len(waveform) or not 1 <= duration <= 1000
            or preview.get('time_step_ms') != 1.0
            or type(neurons) is not int or not 1 <= neurons <= 166700
            or not isinstance(events, list) or len(events) != duration + 1
            or any(type(value) is not int or not 0 <= value <= neurons for value in events)
            or not isinstance(control, list) or len(control) != duration + 1
            or any(type(value) is not int or not 0 <= value <= neurons for value in control)
            or control[0] != 0
            or events[0] != 0 or type(preview.get('spike_count')) is not int
            or sum(events) != preview['spike_count']
            or type(preview.get('active_neurons')) is not int
            or not 0 <= preview['active_neurons'] <= min(neurons, preview['spike_count'])
            or any(type(value) is not int or not 0 <= value <= neurons for value in exclusions)
            or 'recording' not in preview or preview['recording'] is not None):
        raise InvalidFieldProxyManifest('field_proxy_preview')
