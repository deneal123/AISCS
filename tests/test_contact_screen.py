import hashlib
import json
import sqlite3

import numpy as np
import pytest

from scripts.audit_morphology_radii import audit as audit_radii
from scripts.build_morphology_bounds import build_index
from scripts.build_morphology_radii import build as build_radii
from service.infrastructure.stimulation.contacts.screen import (
    screen_contact_positions,
    screen_contacts,
)


def fixture_indexes(tmp_path, monkeypatch):
    swcs = {
        1: '1 1 0 0 0 1250 -1\n2 3 1250 0 0 1250 1\n',
        2: '1 1 125000 0 0 1 -1\n2 3 126250 0 0 1 1\n',
    }
    data = {body: {'swc': swc, 'sha256': hashlib.sha256(swc.encode()).hexdigest(),
                   'bounds_um': [[0, 10], [0, 0], [0, 0]] if body == 1
                   else [[1000, 1010], [0, 0], [0, 0]]} for body, swc in swcs.items()}

    def read(body, _directories, **kwargs):
        if kwargs.get('expected_sha256') not in (None, data[body]['sha256']):
            raise ValueError('changed')
        return data[body]

    for name in ('scripts.build_morphology_bounds', 'scripts.build_morphology_radii',
                 'scripts.audit_morphology_radii',
                 'service.infrastructure.stimulation.contacts.screen'):
        monkeypatch.setattr(name + '.read_skeleton', read)
    bounds, bproof = tmp_path / 'bounds.db', tmp_path / 'bounds.audit.json'
    radii, rproof = tmp_path / 'radii.db', tmp_path / 'radii.audit.json'
    build_index([1, 2], [], bounds, 'graph')
    bproof.write_text(json.dumps({'format': 'malecns-bounds-audit-v1', 'verified': 2,
                                  'index_sha256': hashlib.sha256(bounds.read_bytes()).hexdigest(),
                                  'graph_sha256': 'graph'}))
    build_radii(bounds, bproof, radii, [])
    rproof.write_text(json.dumps(audit_radii(bounds, bproof, radii, [])))
    return bounds, bproof, radii, rproof


def test_contact_screen_expands_by_radius_for_all_four_contacts(tmp_path, monkeypatch):
    indexes = fixture_indexes(tmp_path, monkeypatch)
    points = [[5, 11, 0], [2000, 0, 0], [5, -11, 0], [3000, 0, 0]]
    result = screen_contacts(*indexes, [1, 2], 'graph', [], points, 1.)
    assert result['indexed'] == 2 and result['examined'] == 1
    assert result['potential_intersections'][0]['body_id'] == 1
    assert result['potential_intersections'][0]['contact_indices'] == [0, 2]
    distances = np.asarray(result['potential_intersections'][0]['conservative_clearance_um'])
    assert distances[[0, 2]] == pytest.approx([1., 1.])


def test_contact_screen_rejects_changed_or_incomplete_audit(tmp_path, monkeypatch):
    bounds, bproof, radii, rproof = fixture_indexes(tmp_path, monkeypatch)
    args = (bounds, bproof, radii, rproof, [1, 2], 'graph', [], [[0, 20, 0]] * 4, 1.)
    proof = json.loads(rproof.read_text())
    proof['verified'] = 1
    rproof.write_text(json.dumps(proof))
    with pytest.raises(ValueError, match='Audit reports'):
        screen_contacts(*args)
    proof['verified'] = 2
    rproof.write_text(json.dumps(proof))
    with sqlite3.connect(radii) as db:
        db.execute('UPDATE radii SET radius_um = 0 WHERE body_id = 1')
    with pytest.raises(ValueError, match='changed'):
        screen_contacts(*args)


def test_contact_screen_releases_index_handles_after_query(tmp_path, monkeypatch):
    import gc

    bounds, bproof, radii, rproof = fixture_indexes(tmp_path, monkeypatch)
    # The index-building fixture has its own independent SQLite connections.
    gc.collect()
    screen_contacts(bounds, bproof, radii, rproof, [1, 2], 'graph', [], [[0, 20, 0]] * 4, 1.)
    for index in (bounds, radii):
        renamed = index.with_suffix('.moved')
        index.replace(renamed)
        renamed.replace(index)


def test_screen_matches_independent_segment_distance_at_random_contacts(tmp_path, monkeypatch):
    indexes = fixture_indexes(tmp_path, monkeypatch)
    rng = np.random.default_rng(4951)
    for _ in range(40):
        points = rng.uniform([-15, -15, -15], [1025, 15, 15], (4, 3))
        points[0] = rng.uniform([-5, -12, -12], [15, 12, 12])
        result = screen_contacts(*indexes, [1, 2], 'graph', [], points, 1.)
        expected = {}
        for body, left, right, radius in [(1, 0., 10., 10.), (2, 1000., 1010., .008)]:
            indices = []
            for index, (x, y, z) in enumerate(points):
                closest_x = max(left, min(right, x))
                distance = ((x - closest_x) ** 2 + y ** 2 + z ** 2) ** .5
                if distance - radius <= 1.:
                    indices.append(index)
            if indices:
                expected[body] = indices
        assert {row['body_id']: row['contact_indices']
                for row in result['potential_intersections']} == expected


def test_segment_filter_uses_all_contacts_and_maximum_audited_radius(tmp_path, monkeypatch):
    indexes = fixture_indexes(tmp_path, monkeypatch)
    points = [[5, 11, 0], [2000, 0, 0], [5, -11, 0], [3000, 0, 0]]
    args = (*indexes, [1, 2], 'graph', [], points, 1.)
    expected = screen_contacts(*args)
    seen = {}

    def segment_filter(_index, _audit, **kwargs):
        seen.update(kwargs)
        return {0}, 'c' * 64

    monkeypatch.setattr('service.infrastructure.stimulation.contacts.screen.segment_ordinals',
                        segment_filter)
    result = screen_contacts(*args, segment_index=tmp_path / 'segments',
                             segment_audit=tmp_path / 'audit')
    assert result['potential_intersections'] == expected['potential_intersections']
    np.testing.assert_array_equal(seen['contacts'], points)
    assert seen['radius_um'] == pytest.approx(11.)
    assert result['index_sha256']['segments'] == 'c' * 64
    with pytest.raises(ValueError, match='Both segment'):
        screen_contacts(*args, segment_index=tmp_path / 'segments')
    with pytest.raises(ValueError, match='overflow'):
        screen_contacts(*indexes, [1, 2], 'graph', [], [[1e308, 0, 0]] * 4, 1e308,
                        segment_index=tmp_path / 'segments', segment_audit=tmp_path / 'audit')


def test_position_screen_matches_individual_four_contact_queries(tmp_path, monkeypatch):
    indexes = fixture_indexes(tmp_path, monkeypatch)
    points = [[5, y, 0] for y in (0, 10, 11, 12, 20, -11, -12)]
    args = (*indexes, [1, 2], 'graph', [])
    batched = screen_contact_positions(*args, points, 1.)
    actual = {index for row in batched['potential_intersections']
              for index in row['contact_indices']}
    expected = set()
    for index, point in enumerate(points):
        single = screen_contacts(*args, [point] * 4, 1.)
        if single['potential_intersections']:
            expected.add(index)
    assert actual == expected == {0, 1, 2, 5}
    for invalid in ([], [[0, 0, 0]] * 65):
        with pytest.raises(ValueError, match='Invalid contacts'):
            screen_contact_positions(*args, invalid, 1.)
    with pytest.raises(ValueError, match='Invalid contacts'):
        screen_contacts(*args, points, 1.)


def test_batched_screen_limits_distance_work_without_changing_full_result(tmp_path, monkeypatch):
    indexes = fixture_indexes(tmp_path, monkeypatch)
    from service.infrastructure.stimulation.contacts import screen as contact_screen

    original = contact_screen.contact_clearances
    call_sizes = []
    parsed_sources = []

    def record(swc, contacts, **kwargs):
        call_sizes.append(len(contacts))
        parsed_sources.append(swc)
        return original(swc, contacts, **kwargs)

    monkeypatch.setattr(contact_screen, 'contact_clearances', record)
    points = [[5, 11, 0], [5, 12, 0]] + [[100 + 20 * i, 0, 0] for i in range(46)]
    result = screen_contact_positions(*indexes, [1, 2], 'graph', [], points, 1.)
    row = next(row for row in result['potential_intersections'] if row['body_id'] == 1)
    assert row['contact_indices'] == [0]
    assert len(row['conservative_clearance_um']) == len(points)
    assert row['conservative_clearance_um'] == pytest.approx(
        [((max(0, abs(x - 5) - 5)) ** 2 + y ** 2 + z ** 2) ** .5 - 10
         for x, y, z in points])
    assert all(size == len(points) for size in call_sizes)
    assert len(parsed_sources) == len(set(parsed_sources))  # each candidate is parsed once


def test_screen_probe_short_circuits_only_when_all_candidates_are_clear():
    from service.infrastructure.stimulation.spatial_candidates import closest_swc_segment

    swc = '1 1 0 0 0 125 -1\n2 3 1250 0 0 125 1\n'
    contacts = [[5, 10, 0], [5, 0, 0]]
    assert closest_swc_segment(swc, contacts, probe_indices=[0], probe_clearance_um=1) is None
    screened = closest_swc_segment(swc, contacts, probe_indices=[1], probe_clearance_um=1)
    assert screened == closest_swc_segment(swc, contacts)


@pytest.mark.parametrize('swc', [
    '1 1 0 0 0 125 -1\n2 3 1250 0 0 250 1\n3 3 1250 500 0 60 2\n',
    '1 1 0 0 0 125 -1\n2 3 0 0 0 250 1\n3 1 1000 0 0 10 -1\n',
    '1 1 0 0 0 125 -1\n',
])
def test_fast_clearances_match_previous_geometry_for_all_probes(swc):
    from service.infrastructure.stimulation.contacts.clearances import contact_clearances
    from service.infrastructure.stimulation.spatial_candidates import closest_swc_segment

    rng = np.random.default_rng(921)
    points = rng.uniform(-15, 15, (16, 3)).tolist()
    points[:4] = [[0., 0., 0.], [0., 2., 0.], [10., 0., 0.], [11., 0., 0.]]
    reference = closest_swc_segment(swc, points[:2], recording_contacts=points[2:4],
                                    extra_contacts=points[4:])
    values = (reference['conservative_clearance_um'] + reference['recording_clearance_um']
              + reference['extra_clearance_um'])
    assert contact_clearances(swc, points) == pytest.approx(values, abs=1e-12)
    for probe in ([0], [1, 2, 3], [7, 12]):
        actual = contact_clearances(swc, points, probe_indices=probe, probe_clearance_um=1.)
        if all(values[index] > 1. for index in probe):
            assert actual is None
        else:
            assert actual == pytest.approx(values, abs=1e-12)
            assert [i for i, value in enumerate(actual) if value <= 1.] == [
                i for i, value in enumerate(values) if value <= 1.
            ]


@pytest.mark.parametrize('swc', [
    '', '1 1 0 0 0 1 -1\n1 1 0 0 0 1 -1\n', '1 1 0 0 0 -1 -1\n',
    '1 1 0 0 0 1 7\n', '1 1 nan 0 0 1 -1\n', '1 1 0 0\n',
])
def test_fast_clearances_reject_invalid_sources(swc):
    from service.infrastructure.stimulation.contacts.clearances import contact_clearances

    with pytest.raises(ValueError):
        contact_clearances(swc, [[0., 0., 0.]])


def test_fast_clearances_preserve_randomized_topologies_and_contact_decisions():
    from service.infrastructure.stimulation.contacts.clearances import (
        contact_clearances,
        packed_contact_clearances,
    )
    from service.infrastructure.stimulation.morphology_field import _parse_swc_geometry
    from service.infrastructure.stimulation.spatial_candidates import closest_swc_segment

    rng = np.random.default_rng(19071)
    for _ in range(80):
        count = int(rng.integers(1, 18))
        lines = []
        for node in range(1, count + 1):
            parent = -1 if node == 1 or rng.random() < .15 else int(rng.integers(1, node))
            x, y, z = rng.integers(-1000, 1001, size=3)
            radius = int(rng.integers(0, 300))
            lines.append(f'{node} 3 {x} {y} {z} {radius} {parent}')
        swc = '\n'.join(lines) + '\n'
        points = rng.uniform(-10., 10., (8, 3)).tolist()
        old = closest_swc_segment(swc, points[:2], recording_contacts=points[2:4],
                                  extra_contacts=points[4:])
        expected = (old['conservative_clearance_um'] + old['recording_clearance_um']
                    + old['extra_clearance_um'])
        new = contact_clearances(swc, points)
        assert new == pytest.approx(expected, abs=1e-12)
        packed = packed_contact_clearances(_parse_swc_geometry(swc), points)
        assert packed == pytest.approx(expected, abs=1e-12)
        assert [i for i, value in enumerate(new) if value <= 1.] == [
            i for i, value in enumerate(expected) if value <= 1.
        ]


def test_packed_contact_clearances_reject_invalid_geometry():
    from service.infrastructure.stimulation.contacts.clearances import packed_contact_clearances

    point = [[0., 0., 0.]]
    for geometry in [([], [], [], []), ([1], [[0., 0., 0.]], [4], [1.]),
                     ([1], [[0., float('nan'), 0.]], [-1], [1.]),
                     ([1], [[0., 0., 0.]], [-1], [-1.]),
                     ([1], np.zeros((1, 3), np.float32), [-1], [1.]),
                     (['1'], [[0., 0., 0.]], [-1], [1.])]:
        with pytest.raises(ValueError, match='Invalid packed geometry'):
            packed_contact_clearances(geometry, point)
