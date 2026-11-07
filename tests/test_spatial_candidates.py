import hashlib
import json
import math
import random

import pytest

from scripts.build_morphology_bounds import build_index
from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.point_field import validate_segment_clearance
from service.infrastructure.stimulation.spatial_candidates import (
    closest_swc_segment,
    spatial_candidates,
)

SWC = "1 1 0 0 0 1 -1\n2 1 1250 0 0 1 1\n"
SKELETON = {"sha256": "a" * 64, "bounds_um": [[0, 10], [0, 0], [0, 0]], "swc": SWC}


def report_for(path, count):
    report = path.with_suffix(".audit.json")
    report.write_text(json.dumps({"format": "malecns-bounds-audit-v1", "verified": count,
                                  "index_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                  "graph_sha256": "graph"}), encoding="utf-8")
    return report


def test_exact_segment_distance_is_not_vertex_distance():
    result = closest_swc_segment(SWC, [[5, 1, 0], [100, 0, 0]])
    assert result["distance_um"] == pytest.approx(1)
    assert result["edge_fraction"] == pytest.approx(.5)
    assert result["child_node_id"] == 2
    assert result["contact"] == 0


def test_snapshot_query_rejects_incomplete_and_changed_sources(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.build_morphology_bounds.read_skeleton", lambda *_: SKELETON)
    monkeypatch.setattr("service.infrastructure.stimulation.spatial_candidates.read_skeleton",
                        lambda *_, **__: SKELETON)
    path = tmp_path / "index.sqlite"
    build_index([1, 2], [], path, "graph", limit=1)
    report = report_for(path, 2)
    with pytest.raises(ValueError, match="incomplete"):
        spatial_candidates(path, [1, 2], "graph", [], [[5, 1, 0], [100, 0, 0]], 2,
                           audit_report=report)
    build_index([1, 2], [], path, "graph")
    with pytest.raises(ValueError, match="changed since"):
        spatial_candidates(path, [1, 2], "graph", [], [[5, 1, 0], [100, 0, 0]], 2,
                           audit_report=report)
    report = report_for(path, 2)
    result = spatial_candidates(path, [1, 2], "graph", [], [[5, 1, 0], [100, 0, 0]], 2,
                                audit_report=report)
    assert [row["body_id"] for row in result["candidates"]] == [1, 2]
    assert result["candidates"][0]["distance_um"] == pytest.approx(1)
    outside = spatial_candidates(path, [1, 2], "graph", [], [[5, 3, 0], [100, 0, 0]], 2,
                                 audit_report=report)
    assert outside["candidates"] == []
    monkeypatch.setattr("service.infrastructure.stimulation.spatial_candidates.read_skeleton",
                        lambda *_, **__: (_ for _ in ()).throw(ValueError("digest mismatch")))
    with pytest.raises(ValueError, match="changed"):
        spatial_candidates(path, [1, 2], "graph", [], [[5, 1, 0], [100, 0, 0]], 2,
                           audit_report=report)


def test_isolated_root_has_no_fabricated_cable():
    result = closest_swc_segment("1 1 0 0 0 1 -1\n", [[0, 0, 0], [3, 0, 0]])
    assert result["isolated_root"] is True
    assert result["child_node_id"] is None
    assert result["geometry"]["isolated_roots"] == 1


def test_geometry_flags_capture_solver_incompatibilities():
    swc = ("1 1 0 0 0 1 -1\n2 1 0 0 0 1 1\n"
           "3 1 100 0 0 0 2\n4 1 200 0 0 1 -1\n")
    result = closest_swc_segment(swc, [[0, 0, 0], [3, 0, 0]])
    assert result["geometry"] == {"components": 2, "isolated_roots": 1,
                                  "zero_length_edges": 1, "nonpositive_radius_edges": 1}


def test_clearance_accounts_for_conservative_cable_radius():
    swc = "1 1 0 0 0 125 -1\n2 1 1250 0 0 125 1\n"
    contacts = [[5, 1.5, 0], [100, 0, 0]]
    result = closest_swc_segment(swc, contacts)
    assert result["distance_um"] == pytest.approx(1.5)
    assert result["conservative_clearance_um"][0] == pytest.approx(.5)
    with pytest.raises(ValueError, match="intersects"):
        validate_segment_clearance([[0, 0, 0]], [[10, 0, 0]], contacts, 1, [[1, 1]])


def test_recording_contacts_do_not_change_stimulation_selection():
    stim = [[5, 3, 0], [5, 2, 0]]
    recording = [[5, 0, 0], [5, 10, 0]]
    result = closest_swc_segment(SWC, stim, recording_contacts=recording)
    assert result["contact"] == 1
    assert result["distance_um"] == pytest.approx(2)
    assert result["edge_fraction"] == pytest.approx(.5)
    assert result["conservative_clearance_um"] == pytest.approx([2.992, 1.992])
    assert result["recording_clearance_um"] == pytest.approx([-.008, 9.992])


def test_extra_positions_preserve_stim_selection_and_report_clearances():
    stim = [[5, 2, 0], [100, 0, 0]]
    recording = [[5, 3, 0], [5, 4, 0]]
    baseline = closest_swc_segment(SWC, stim, recording_contacts=recording)
    result = closest_swc_segment(SWC, stim, recording_contacts=recording,
                                 extra_contacts=[[5, 0, 0], [5, 8, 0]])
    for key in ("distance_um", "child_node_id", "contact", "edge_fraction"):
        assert result[key] == baseline[key]
    assert result["recording_clearance_um"] == baseline["recording_clearance_um"]
    assert result["extra_clearance_um"] == pytest.approx([-.008, 7.992])
    with pytest.raises(ValueError, match="additional contacts"):
        closest_swc_segment(SWC, stim, extra_contacts=[[5, 0, 0]])


def test_search_returns_recording_clearance_for_each_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.build_morphology_bounds.read_skeleton", lambda *_: SKELETON)
    monkeypatch.setattr("service.infrastructure.stimulation.spatial_candidates.read_skeleton",
                        lambda *_, **__: SKELETON)
    path = tmp_path / "index.sqlite"
    build_index([1], [], path, "graph")
    result = spatial_candidates(path, [1], "graph", [], [[5, 1, 0], [100, 0, 0]], 2,
                                audit_report=report_for(path, 1),
                                recording_contacts=[[5, .1, 0], [5, 20, 0]])
    clearance = result["candidates"][0]["recording_clearance_um"]
    assert clearance == pytest.approx([.092, 19.992])
    with pytest.raises(ValueError, match="recording contacts"):
        spatial_candidates(path, [1], "graph", [], [[5, 1, 0], [100, 0, 0]], 2,
                           audit_report=report_for(path, 1), recording_contacts=[[1, 2, 3]])


def test_indexed_query_matches_independent_brute_force_across_positions(tmp_path, monkeypatch):
    rng = random.Random(4307)
    skeletons, segments = {}, {}
    for body in range(1, 41):
        start = [rng.randint(-12500, 12500) for _ in range(3)]
        end = [rng.randint(-12500, 12500) for _ in range(3)]
        swc = (f"1 1 {' '.join(map(str, start))} 1 -1\n"
               f"2 1 {' '.join(map(str, end))} 1 1\n")
        a = [value * .008 for value in start]
        b = [value * .008 for value in end]
        bounds = [[min(a[axis], b[axis]), max(a[axis], b[axis])] for axis in range(3)]
        skeletons[body] = {"sha256": hashlib.sha256(swc.encode()).hexdigest(),
                           "bounds_um": bounds, "swc": swc}
        segments[body] = (a, b)

    def read(body, _directories, **_kwargs):
        return skeletons[body]

    def independent_distance(a, b, point):
        delta = [end - start for start, end in zip(a, b, strict=True)]
        norm = sum(value * value for value in delta)
        fraction = 0 if norm == 0 else max(0, min(1, sum(
            (position - start) * value
            for start, position, value in zip(a, point, delta, strict=True)
        ) / norm))
        return math.sqrt(sum((start + fraction * value - position) ** 2
                             for start, value, position in zip(a, delta, point, strict=True)))

    monkeypatch.setattr("scripts.build_morphology_bounds.read_skeleton", read)
    monkeypatch.setattr("service.infrastructure.stimulation.spatial_candidates.read_skeleton", read)
    ids = list(skeletons)
    path = tmp_path / "random.sqlite"
    build_index(ids, [], path, "graph")
    report = report_for(path, len(ids))
    for _ in range(60):
        contacts = [[rng.uniform(-150, 150) for _ in range(3)] for _ in range(2)]
        radius = rng.uniform(0, 100)
        expected = {body for body, (a, b) in segments.items()
                    if min(independent_distance(a, b, contact) for contact in contacts) <= radius}
        actual = spatial_candidates(path, ids, "graph", [], contacts, radius, audit_report=report)
        assert {item["body_id"] for item in actual["candidates"]} == expected


def test_parallel_query_matches_serial_and_rejects_changed_snapshot(tmp_path):
    root = tmp_path / "source"
    (root / "raw").mkdir(parents=True)
    (root / "receipts").mkdir()
    for body in (1, 2, 3):
        raw = f"1 1 {body * 100} 0 0 1 -1\n2 1 {body * 100 + 100} 0 0 1 1\n".encode()
        (root / "raw" / f"{body}.swc").write_bytes(raw)
        receipt = {"body_id": body, "url": BASE + f"{body}.swc",
                   "sha256": hashlib.sha256(raw).hexdigest()}
        (root / "receipts" / f"{body}.json").write_text(json.dumps(receipt))
    path = tmp_path / "index.sqlite"
    build_index([1, 2, 3], [root], path, "graph")
    report = report_for(path, 3)
    args = (path, [1, 2, 3], "graph", [root], [[2, 0, 0], [3, 0, 0]], 10)
    serial = spatial_candidates(*args, audit_report=report)
    parallel = spatial_candidates(*args, audit_report=report, workers=2)
    assert parallel == serial
    (root / "raw" / "2.swc").write_text("1 1 0 0 0 1 -1\n")
    with pytest.raises(ValueError, match="changed"):
        spatial_candidates(*args, audit_report=report, workers=2)
    with pytest.raises(ValueError, match="workers"):
        spatial_candidates(*args, audit_report=report, workers=0)
