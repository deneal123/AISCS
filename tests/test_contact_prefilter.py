"""The optional broad phase must preserve the exact narrow-phase result."""

import builtins

import numpy as np
import pytest

from service.infrastructure.stimulation.contacts import clearances as clearance_module
from service.infrastructure.stimulation.contacts.clearances import packed_contact_clearances

pytest.importorskip('numba')

from service.infrastructure.stimulation.contacts.broad_phase import may_intersect_box  # noqa: E402


def _geometry(points, parents, radii):
    points = np.asarray(points, dtype=np.float64)
    return (np.arange(1, len(points) + 1, dtype=np.int64), points,
            np.asarray(parents, dtype=np.int64), np.asarray(radii, dtype=np.float64))


def _compare(geometry, contacts, probes, clearance):
    args = dict(probe_indices=probes, probe_clearance_um=clearance)
    expected = packed_contact_clearances(geometry, contacts, **args)
    actual = packed_contact_clearances(geometry, contacts, _conservative_prefilter=True, **args)
    assert actual == expected
    if expected is not None:
        assert may_intersect_box(geometry[1], geometry[2], geometry[3],
                                 np.asarray(contacts, dtype=np.float64),
                                 np.asarray(probes, dtype=np.int64), clearance)


def test_seeded_geometries_and_multiple_probe_orders():
    rng = np.random.default_rng(93421)
    for _ in range(300):
        count = int(rng.integers(1, 35))
        points = rng.normal(size=(count, 3)) * 20
        parents = np.array([-1] + [int(rng.integers(-1, i)) for i in range(1, count)])
        radii = rng.uniform(0, 3, size=count)
        contacts = rng.normal(size=(4, 3)) * 30
        if count > 1 and rng.random() < .4:
            points[-1] = points[max(parents[-1], 0)]
        if rng.random() < .5:
            contacts[int(rng.integers(0, 4))] = points[int(rng.integers(0, count))]
        _compare(_geometry(points, parents, radii), contacts, [2, 0, 3], 1.)


@pytest.mark.parametrize('distance', [1 - 1e-12, 1, 1 + 1e-12, 1.001, 4])
def test_near_boundary_and_isolated_root(distance):
    geometry = _geometry([[0, 0, 0]], [-1], [0])
    _compare(geometry, [[distance, 0, 0], [6, 0, 0]], [0], 1.)


def test_degenerate_segment_varying_radii_and_probe_order():
    geometry = _geometry([[0, 0, 0], [0, 0, 0], [4, 0, 0]], [-1, 0, 1], [0, .5, 2])
    _compare(geometry, [[0, 3, 0], [5, 0, 0], [20, 0, 0]], [2, 1], 1.)


def test_boundary_decisions_at_different_coordinate_scales():
    rng = np.random.default_rng(9824)
    for scale in (1e-8, 1., 1e3, 1e4):
        for _ in range(50):
            start = rng.uniform(-scale, scale, size=3)
            direction = rng.normal(size=3)
            direction /= np.linalg.norm(direction)
            end = start + direction * max(scale * .01, 1e-7)
            normal = np.cross(direction, [1., 0., 0.])
            if np.linalg.norm(normal) < .01:
                normal = np.cross(direction, [0., 1., 0.])
            normal /= np.linalg.norm(normal)
            radius = float(rng.uniform(0., 2.))
            geometry = _geometry([start, end], [-1, 0], [radius, radius])
            for offset in (-1e-10, 0., 1e-10):
                contact = (start + end) / 2 + normal * (radius + 1. + offset)
                _compare(geometry, [contact], [0], 1.)


def test_out_of_range_and_negative_clearance_use_reference():
    _compare(_geometry([[1e6, 0, 0]], [-1], [0]), [[0, 0, 0]], [0], 1.)
    _compare(_geometry([[0, 0, 0]], [-1], [0]), [[5, 0, 0]], [0], -1.)


def test_extreme_segment_preserves_reference_numerical_error():
    geometry = _geometry([[1e200, 0, 0], [-1e200, 0, 0]], [-1, 0], [0, 0])
    for flag in [False, True]:
        with pytest.raises(ValueError, match='Segment geometry exceeds numerical range'):
            packed_contact_clearances(geometry, [[0, 0, 0]], probe_indices=[0],
                                      probe_clearance_um=1., _conservative_prefilter=flag)


def test_invalid_geometry_remains_an_error():
    geometry = _geometry([[float('nan'), 0, 0]], [-1], [0])
    for flag in [False, True]:
        with pytest.raises(ValueError, match='Invalid packed geometry'):
            packed_contact_clearances(geometry, [[0, 0, 0]], probe_indices=[0],
                                      probe_clearance_um=1., _conservative_prefilter=flag)


def test_no_probe_preserves_complete_clearances():
    geometry = _geometry([[0, 0, 0], [1, 0, 0]], [-1, 0], [.2, .2])
    contacts = [[10, 1, 0], [0, 1, 0]]
    assert packed_contact_clearances(geometry, contacts, _conservative_prefilter=True) == (
        packed_contact_clearances(geometry, contacts))


def test_clear_box_skips_only_the_expensive_narrow_phase(monkeypatch):
    geometry = _geometry([[0, 0, 0], [1, 0, 0]], [-1, 0], [.2, .2])
    calls = []
    original = clearance_module._geometry_clearances

    def observed(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(clearance_module, '_geometry_clearances', observed)
    assert packed_contact_clearances(geometry, [[100, 100, 100]], probe_indices=[0],
                                     probe_clearance_um=1., _conservative_prefilter=True) is None
    assert not calls
    near = packed_contact_clearances(geometry, [[0, 0, 0]], probe_indices=[0],
                                     probe_clearance_um=1., _conservative_prefilter=True)
    assert near is not None
    assert calls == [True]


def test_missing_optional_numba_falls_back_to_exact_path(monkeypatch):
    geometry = _geometry([[0, 0, 0]], [-1], [0])
    expected = packed_contact_clearances(geometry, [[.5, 0, 0]], probe_indices=[0],
                                         probe_clearance_um=1.)
    original_import = builtins.__import__

    def missing_numba(name, *args, **kwargs):
        if name == 'service.infrastructure.stimulation.contacts.broad_phase':
            raise ModuleNotFoundError('No module named numba', name='numba')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', missing_numba)
    actual = packed_contact_clearances(geometry, [[.5, 0, 0]], probe_indices=[0],
                                       probe_clearance_um=1., _conservative_prefilter=True)
    assert actual == expected


def test_broken_numba_dependency_is_not_silenced(monkeypatch):
    original_import = builtins.__import__

    def broken_dependency(name, *args, **kwargs):
        if name == 'service.infrastructure.stimulation.contacts.broad_phase':
            raise ModuleNotFoundError('No module named llvmlite', name='llvmlite')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', broken_dependency)
    geometry = _geometry([[0, 0, 0]], [-1], [0])
    with pytest.raises(ModuleNotFoundError, match='llvmlite'):
        packed_contact_clearances(geometry, [[.5, 0, 0]], probe_indices=[0],
                                  probe_clearance_um=1., _conservative_prefilter=True)
