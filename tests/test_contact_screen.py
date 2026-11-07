import hashlib
import json
import sqlite3

import numpy as np
import pytest

from scripts.audit_morphology_radii import audit as audit_radii
from scripts.build_morphology_bounds import build_index
from scripts.build_morphology_radii import build as build_radii
from service.infrastructure.stimulation.contact_screen import (
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
                 'service.infrastructure.stimulation.contact_screen'):
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

    monkeypatch.setattr('service.infrastructure.stimulation.contact_screen.segment_ordinals',
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
    from service.infrastructure.stimulation import contact_screen

    original = contact_screen.closest_swc_segment
    call_sizes = []
    parsed_sources = []

    def record(swc, contacts, **kwargs):
        call_sizes.append(4 + len(kwargs.get('extra_contacts') or []))
        parsed_sources.append(swc)
        return original(swc, contacts, **kwargs)

    monkeypatch.setattr(contact_screen, 'closest_swc_segment', record)
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
