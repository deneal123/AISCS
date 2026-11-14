from dataclasses import dataclass

import numpy as np
import pytest

from service.application.population.bulk_recording_execution import execute_bulk_recording
from service.application.population.bulk_recording_export import read_bulk_recording


@dataclass
class Parameters:
    current_na: float = -300.


def numerical_options():
    return {'params': Parameters(), 'time_ms': [0., .05, .1], 'expected_ids': [1, 2],
            'electrode_um': [1., 2., 3.], 'reference_um': [4., 5., 6.],
            'conductivity_s_m': .3, 'clearance_um': 1.}


def test_execution_publishes_preview_and_authenticated_trace(tmp_path, monkeypatch):
    output = tmp_path / 'result.npz'
    result = {'time_ms': np.array([0., .05, .1]), 'neural_uv': np.array([0., 1., -1.]),
              'cells': 2, 'replacement_receipts': [],
              'interpretation': 'independent cells; no network feedback'}
    monkeypatch.setattr('service.application.population.bulk_recording_execution.run_bulk_recording',
                        lambda *_a, **_k: result)
    response = execute_bulk_recording({'graph_sha256': 'a' * 64}, [0., 1., 0.], [[1.]],
                                      **numerical_options(), output_path=output,
                                      graph_sha256='a' * 64,
                                      configuration_sha256='b' * 64)
    assert response['preview']['neural_uv'] == [0., 1., -1.]
    restored = read_bulk_recording(output, sha256=response['artifact']['sha256'],
                                   graph_sha256='a' * 64, configuration_sha256='b' * 64)
    np.testing.assert_array_equal(restored['neural_uv'], result['neural_uv'])
    assert len(restored['numerical_inputs_sha256']) == 64


def test_execution_failure_preserves_previous_artifact(tmp_path, monkeypatch):
    output = tmp_path / 'result.npz'
    output.write_bytes(b'previous')
    monkeypatch.setattr('service.application.population.bulk_recording_execution.run_bulk_recording',
                        lambda *_a, **_k: {'cells': 1})
    with pytest.raises(ValueError, match='preview'):
        execute_bulk_recording({'graph_sha256': 'a' * 64}, [0., 1., 0.], [[1.]],
                               **numerical_options(), output_path=output,
                               graph_sha256='a' * 64, configuration_sha256='b' * 64)
    assert output.read_bytes() == b'previous'


def test_execution_rejects_graph_mismatch_before_running(tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError('Solver must not run')
    monkeypatch.setattr('service.application.population.bulk_recording_execution.run_bulk_recording',
                        fail)
    with pytest.raises(ValueError, match='graph identity'):
        execute_bulk_recording({'graph_sha256': 'c' * 64}, [], [],
                               output_path=tmp_path / 'result.npz',
                               graph_sha256='a' * 64, configuration_sha256='b' * 64)
    with pytest.raises(ValueError, match='configuration identity'):
        execute_bulk_recording({'graph_sha256': 'a' * 64}, [], [],
                               output_path=tmp_path / 'result.npz',
                               graph_sha256='a' * 64, configuration_sha256='invalid')
