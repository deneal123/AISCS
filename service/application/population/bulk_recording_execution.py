"""Experimental independent-population recording application workflow."""

from .bulk_numerical_identity import numerical_inputs_sha256
from .bulk_recording import run_bulk_recording
from .bulk_recording_export import export_bulk_recording
from .bulk_recording_preview import bulk_recording_preview


def execute_bulk_recording(metadata, stimulus, rate_table, *, output_path, graph_sha256,
                           configuration_sha256,
                           **kwargs):
    """Solve, prepare preview and atomically publish the verified trace.

    An exception before publication leaves any previous trace untouched.
    This is not a coupled network or a simulator API endpoint.
    """
    if (not isinstance(metadata, dict) or metadata.get('graph_sha256') != graph_sha256
            or not isinstance(graph_sha256, str) or len(graph_sha256) != 64
            or any(char not in '0123456789abcdef' for char in graph_sha256)):
        raise ValueError('Population cache graph identity mismatch')
    if (not isinstance(configuration_sha256, str) or len(configuration_sha256) != 64
            or any(char not in '0123456789abcdef' for char in configuration_sha256)):
        raise ValueError('Invalid configuration identity')
    inputs_hash = numerical_inputs_sha256(params=kwargs['params'], stimulus=stimulus,
        rate_table=rate_table, time_ms=kwargs['time_ms'], expected_ids=kwargs['expected_ids'],
        electrode_um=kwargs['electrode_um'], reference_um=kwargs['reference_um'],
        conductivity_s_m=kwargs['conductivity_s_m'], clearance_um=kwargs['clearance_um'])
    result = run_bulk_recording(metadata, stimulus, rate_table, **kwargs)
    result['numerical_inputs_sha256'] = inputs_hash
    preview = bulk_recording_preview(result)
    receipt = export_bulk_recording(output_path, result, graph_sha256=graph_sha256,
                                    configuration_sha256=configuration_sha256)
    return {'preview': preview, 'artifact': receipt, 'graph_sha256': graph_sha256,
            'configuration_sha256': configuration_sha256}
