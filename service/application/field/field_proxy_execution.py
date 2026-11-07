"""Experimental field-to-network execution without claiming physical recording."""

import hashlib
import json
from pathlib import Path

import numpy as np

from service.application.field.field_proxy_preview import field_proxy_preview
from service.infrastructure.connectome import field_proxy, kernel
from service.infrastructure.connectome.dataset import digest
from service.infrastructure.connectome.forced_export import encode_forced_spikes
from service.infrastructure.stimulation.field_summary_compute import compute
from service.infrastructure.stimulation.field_summary_verified import verified_descriptors
from service.infrastructure.stimulation.field_summary_audit import failure_category
from service.infrastructure.stimulation.fragment_sparse_delta import encode_sparse_delta
from service.infrastructure.stimulation.fragment_target_response import (
    encode_target_response_binary,
)


def execute_field_proxy(graph, directories, *, field_path, output, configuration, gain, seed,
                        waveform, compute_field=False, allow_partial_geometry=False,
                        allow_missing_curvature=False, allow_contact_exclusion=False,
                        capture_delta=False, field_workers=1,
                        progress=None):
    """Compute or verify one field and persist a labelled, reproducible LIF response."""
    if output.exists():
        raise ValueError('Output already exists')
    if progress is not None and not callable(progress):
        raise ValueError('Invalid progress callback')
    graph_hash = graph.provenance['manifest_sha256']
    if compute_field:
        def check_row(row):
            status = row.get('status')
            if status == 'source_missing':
                raise ValueError('field_source_missing')
            if status == 'invalid_geometry_or_field':
                category = failure_category(status, row.get('reason'))
                if category == 'contact_exclusion' and allow_contact_exclusion:
                    return
                raise ValueError('field_contact_exclusion' if category == 'contact_exclusion'
                                 else 'field_invalid_geometry')
            if status == 'partial_geometry' and not allow_partial_geometry:
                raise ValueError('field_partial_geometry')
            if status not in ('ok', 'partial_geometry'):
                raise ValueError('field_invalid_geometry')
            if row.get('max_abs_curvature_signed_mv_per_um2') is None and not allow_missing_curvature:
                raise ValueError('field_missing_curvature')

        if progress is not None:
            progress({'phase': 'field', 'done': 0, 'total': graph.size})
        compute(graph.ids, directories, field_path, configuration, graph_hash=graph_hash,
                allow_degenerate=allow_partial_geometry, workers=field_workers, check_row=check_row,
                progress=(None if progress is None else
                          lambda done, total: progress({'phase': 'field', 'done': done,
                                                        'total': total})))
    if progress is not None:
        progress({'phase': 'field_verification', 'done': 0, 'total': 0})
    desc, provenance = verified_descriptors(field_path, graph.ids, graph_hash,
        allow_partial_geometry=allow_partial_geometry,
        allow_missing_curvature=allow_missing_curvature,
        allow_contact_exclusion=allow_contact_exclusion,
        expected_configuration=configuration)
    if progress is not None:
        progress({'phase': 'network', 'done': 0, 'total': 0})
    run = field_proxy.run_field_proxy(graph, descriptor=desc, waveform=waveform, gain=gain,
                                      seed=seed, capture_sparse_delta=capture_delta)
    output.mkdir(parents=True, exist_ok=False)
    arrays = {key: value for key, value in run.items() if isinstance(value, np.ndarray)}
    np.savez_compressed(output / 'network.npz', **arrays)
    events, description, event_hash = encode_forced_spikes(graph, {
        'metadata': {'graph': graph.provenance, 'duration_ms': len(waveform)},
        'spike_neurons': run['spike_neurons'], 'spike_times_ms': run['spike_times_ms']})
    description['interpretation'] = 'uncalibrated LIF events; not measured neural activity'
    (output / 'network-events.bin').write_bytes(events)
    metadata = {'graph_sha256': graph_hash, 'field': provenance, 'seed': seed, 'gain': gain,
                'waveform': waveform, 'network_sha256': digest(output / 'network.npz'),
                'proxy_source_sha256': digest(Path(field_proxy.__file__)),
                'runner_source_sha256': digest(Path(__file__)),
                'kernel_source_sha256': digest(Path(kernel.__file__)),
                'numpy_version': np.__version__, 'time_step_ms': 1.0,
                'network_weight_gain': 0.075, 'interpretation': run['interpretation']}
    metadata['event_description'] = description
    metadata['event_sha256'] = event_hash
    if capture_delta:
        control_events, control_description, control_hash = encode_forced_spikes(graph, {
            'metadata': {'graph': graph.provenance, 'duration_ms': len(waveform)},
            'spike_neurons': run['control_spike_neurons'],
            'spike_times_ms': run['control_spike_times_ms']})
        (output / 'network-control-events.bin').write_bytes(control_events)
        metadata['control_event_description'] = control_description
        metadata['control_event_sha256'] = control_hash
        identity = {'field_sha256': provenance['file_sha256'], 'gain': gain,
                    'waveform': waveform, 'seed': seed,
                    'proxy_source_sha256': metadata['proxy_source_sha256'],
                    'kernel_source_sha256': metadata['kernel_source_sha256']}
        config_hash = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'),
                                                allow_nan=False).encode()).hexdigest()
        sparse = run['sparse_delta']
        metadata['state_delta'] = {'status': sparse['status'], 'configuration_sha256': config_hash,
            'interpretation': 'relative LIF voltage difference, not spikes or measured voltage'}
        response = encode_target_response_binary(run['target_response'], schedules=[],
            source_ids=[], duration_ms=len(waveform), graph_sha256=graph_hash,
            configuration_sha256=config_hash, network_ids=graph.ids)
        (output / 'state-response.bin').write_bytes(response)
        metadata['state_delta']['sampled_sha256'] = hashlib.sha256(response).hexdigest()
        if sparse['status'] == 'recorded':
            data = encode_sparse_delta(sparse, graph=graph, source_ids=[],
                duration_ms=len(waveform), configuration_sha256=config_hash)
            (output / 'state-delta.bin').write_bytes(data)
            metadata['state_delta']['sha256'] = hashlib.sha256(data).hexdigest()
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2, allow_nan=False) + '\n',
                                          encoding='utf8')
    preview = field_proxy_preview(graph, run, waveform, provenance)
    (output / 'field-proxy-preview.json').write_text(
        json.dumps(preview, allow_nan=False) + '\n', encoding='utf8')
    return metadata
