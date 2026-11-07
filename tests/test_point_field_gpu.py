import numpy as np
import pytest

from service.infrastructure.stimulation import point_field_gpu
from service.infrastructure.stimulation.point_field import bipolar_potential_mv


def test_grouped_gpu_preserves_neuron_order_and_limits_each_batch(monkeypatch):
    calls = []

    def calculate(points, *_args, **_kwargs):
        calls.append(len(points))
        return points[:, 0] * 2

    monkeypatch.setattr(point_field_gpu, 'bipolar_potential_mv_gpu', calculate)
    groups = [np.array([[1., 0., 0.], [2., 0., 0.]]), np.array([[3., 0., 0.]]),
              np.array([[4., 0., 0.], [5., 0., 0.]])]
    result = point_field_gpu.bipolar_potential_groups_gpu(
        groups, [0, 0, 0], [1, 0, 0], 1, .3, clearance_um=1, max_points=3)
    assert calls == [3, 2]
    assert [row.tolist() for row in result] == [[2., 4.], [6.], [8., 10.]]
    with pytest.raises(ValueError, match='point limit'):
        point_field_gpu.bipolar_potential_groups_gpu(
            groups, [0, 0, 0], [1, 0, 0], 1, .3, clearance_um=1, max_points=1)
def test_gpu_path_validates_physical_parameters_before_device_access(monkeypatch):
    monkeypatch.setattr(point_field_gpu, '_kernel', lambda: pytest.fail('device accessed'))
    with pytest.raises(ValueError, match='Conductivity'):
        point_field_gpu.bipolar_potential_mv_gpu([[1, 1, 1]], [0, 0, 0], [20, 0, 0],
                                                1, 0, clearance_um=1)
    with pytest.raises(ValueError, match='three-dimensional'):
        point_field_gpu.bipolar_potential_mv_gpu([[1, 2]], [0, 0, 0], [20, 0, 0],
                                                1, .3, clearance_um=1)


def test_gpu_device_failure_is_not_silently_replaced_with_cpu(monkeypatch):
    def unavailable():
        raise RuntimeError('CUDA field backend is unavailable')

    monkeypatch.setattr(point_field_gpu, '_kernel', unavailable)
    with pytest.raises(RuntimeError, match='CUDA field backend'):
        point_field_gpu.bipolar_potential_mv_gpu(np.array([[3., 3., 3.]]), [0, 0, 0], [20, 0, 0],
                                                1, .3, clearance_um=1)


def test_group_isolation_uses_one_dispatch_and_preserves_failure_per_neuron(monkeypatch):
    calls = []

    def fake(points, *_args, **_kwargs):
        calls.append(len(points))
        return np.array([1., 2., float('nan'), 4.]), np.array([0, 1, 2, 0])

    monkeypatch.setattr(point_field_gpu, '_potential_and_status', fake)
    groups = [np.ones((1, 3)), np.ones((1, 3)), np.ones((1, 3)), np.ones((1, 3))]
    result = point_field_gpu.bipolar_potential_groups_gpu(
        groups, [0, 0, 0], [20, 0, 0], 1, .3, clearance_um=1, isolate_invalid=True)
    assert calls == [4]
    assert result[0].tolist() == [1.]
    assert isinstance(result[1], ValueError) and 'exclusion sphere' in str(result[1])
    assert isinstance(result[2], ValueError) and 'overflow' in str(result[2])
    assert result[3].tolist() == [4.]


def test_real_cuda_matches_cpu_and_rejects_contact_intersection():
    cuda = pytest.importorskip('numba.cuda')
    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    points = np.random.default_rng(4127).uniform(50., 500., size=(100_000, 3))
    args = ([0., 0., 0.], [1000., 0., 0.], -300., .3)
    actual = point_field_gpu.bipolar_potential_mv_gpu(points, *args, clearance_um=1.)
    expected = bipolar_potential_mv(points, *args, clearance_um=1.)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
    with pytest.raises(ValueError, match='exclusion'):
        point_field_gpu.bipolar_potential_mv_gpu([[0., 0., 0.]], *args, clearance_um=1.)


def test_real_cuda_isolates_intersections_without_losing_neighboring_groups():
    cuda = pytest.importorskip('numba.cuda')
    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    args = ([0., 0., 0.], [1000., 0., 0.], -300., .3)
    groups = [np.array([[200., 10., 0.], [201., 10., 0.]]),
              np.array([[0., 0., 0.], [203., 10., 0.]]),
              np.array([[205., 10., 0.]])]
    result = point_field_gpu.bipolar_potential_groups_gpu(
        groups, *args, clearance_um=1., isolate_invalid=True)
    assert isinstance(result[1], ValueError)
    assert 'exclusion sphere' in str(result[1])
    for index in (0, 2):
        np.testing.assert_allclose(result[index], bipolar_potential_mv(
            groups[index], *args, clearance_um=1.), rtol=1e-12, atol=1e-12)
    with pytest.raises(ValueError, match='exclusion'):
        point_field_gpu.bipolar_potential_groups_gpu(groups, *args, clearance_um=1.)
