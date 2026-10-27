"""Source-linked display geometry. The embedding is not anatomical registration."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from service.infrastructure.connectome.dataset import SparseGraph

REGIONS = (
    "brain",
    "thorax",
    "abdomen",
    "front_left",
    "front_right",
    "middle_left",
    "middle_right",
    "hind_left",
    "hind_right",
    "head",
)

# View-only routes in FlyBody millimetres. Peripheral centre-lines are author
# drawings, not traced axons. Numerical recording uses its separate um frame.
BODY_ROUTES = json.loads(Path(__file__).with_name("body-routes.json").read_text())
ROUTES = {
    **BODY_ROUTES["routes"],
    "abdomen": [[-0.38, 0, -0.25], [-0.76, 0, -0.22], [-1.18, 0, -0.16], [-1.56, 0, -0.21]],
    "head": [[0.30, 0, -0.15], [0.67, 0, 0.02], [0.92, 0, 0.06]],
}


def scene_arrays(graph: SparseGraph, counts: np.ndarray) -> tuple[dict, dict]:
    info, n = graph.annotations, graph.size
    raw = np.full((n, 3), np.nan, np.float32)
    kind = np.zeros(n, np.uint8)
    regions = np.zeros(n, np.uint8)
    for i, (soma, root) in enumerate(
        zip(info["somaLocation"], info["tosomaLocation"], strict=True)
    ):
        if soma is not None or root is not None:
            raw[i] = np.asarray(soma if soma is not None else root) * 0.008
            kind[i] = 1 if soma is not None else 2
    known = np.isfinite(raw).all(axis=1)
    # One fixed affine map preserves measured CNS relative geometry. EM axes
    # are displayed in a schematic FlyBody frame, with no physical-fit claim.
    positions = np.zeros((n, 3), np.float32)
    positions[known, 0] = 0.98 - (raw[known, 2] - 180) * 0.00165
    positions[known, 1] = (raw[known, 0] - 393) * 0.0010
    positions[known, 2] = 0.04 - (raw[known, 1] - 200) * 0.0009
    nerves = {"ProLN": "front", "MesoLN": "middle", "MetaLN": "hind"}
    for i in range(n):
        superclass = info["superclass"][i] or ""
        segment = info["somaNeuromere"][i] or ""
        nerve = info["entryNerve"][i] or info["exitNerve"][i] or ""
        side = info["rootSide"][i] or info["somaSide"][i] or ""
        region = "thorax" if superclass.startswith("vnc") else "brain"
        if segment.startswith("A") or nerve.startswith("AbN"):
            region = "abdomen"
        elif nerve in nerves and side in ("L", "R"):
            region = nerves[nerve] + ("_left" if side == "L" else "_right")
        regions[i] = REGIONS.index(region)
        if known[i]:
            continue
        # Missing source positions remain missing in raw_um; the deterministic
        # glyph placement below explicitly has kind=0 (schematic/unknown).
        fraction = int(graph.ids[i] % 1009) / 1008
        if region in ROUTES:
            path = np.asarray(ROUTES[region])
            scaled = fraction * (len(path) - 1)
            first = min(int(scaled), len(path) - 2)
            positions[i] = path[first] * (1 - (scaled - first)) + path[first + 1] * (scaled - first)
            positions[i, 1] += ((int(graph.ids[i] % 37) / 36) - 0.5) * 0.025
        elif region == "thorax":
            positions[i] = [(0.35, -0.12, -0.4)[i % 3], (fraction - 0.5) * 0.12, -0.22]
        else:
            positions[i] = [0.84, (fraction - 0.5) * 0.5, 0.02 + ((i % 53) / 52 - 0.5) * 0.2]
    # All nodes are drawn. Edges alone use a declared display budget. Prefer
    # active presynaptic sources, then cover the remaining graph deterministically.
    degree = np.diff(graph.ptr)
    active = np.flatnonzero((counts > 0) & (degree > 0))
    rest = np.flatnonzero((counts == 0) & (degree > 0))
    budget = 24000
    active = (
        active[np.linspace(0, len(active) - 1, min(len(active), budget)).astype(int)]
        if len(active)
        else active
    )
    room = budget - len(active)
    rest = (
        rest[np.linspace(0, len(rest) - 1, min(len(rest), room)).astype(int)]
        if len(rest) and room
        else np.empty(0, int)
    )
    pres = np.concatenate([active, rest]).astype(np.uint32)
    posts = np.empty(len(pres), np.uint32)
    for j, pre in enumerate(pres):
        first, last = int(graph.ptr[pre]), int(graph.ptr[pre + 1])
        posts[j] = graph.posts[first + np.argmax(graph.counts[first:last])]
    arrays = {
        "node_ids": np.asarray(graph.ids, dtype="<u8"),
        "raw_um": raw,
        "positions_mm": positions,
        "coordinate_kind": kind,
        "regions": regions,
        "edge_pre": pres,
        "edge_post": posts,
        "edge_sign": np.asarray(graph.signs[pres], np.int8),
    }
    metadata = {
        "embedding": "male-cns-flybody-view-only-v2",
        "body_route_provenance": {k: v for k, v in BODY_ROUTES.items() if k != "routes"},
        "regions": list(REGIONS),
        "routes_mm": ROUTES,
        "coordinate_kind": {
            "0": "schematic; no source coordinate",
            "1": "soma",
            "2": "to-soma landmark",
        },
        "source_positioned_nodes": int(known.sum()),
        "schematic_nodes": int((~known).sum()),
        "display_nodes": n,
        "display_edges": len(pres),
        "computed_edges": len(graph.posts),
        "edge_selection": (
            "highest-count outgoing edge per sampled presynaptic node; active sources first"
        ),
        "limitations": [
            "Display affine embedding is not an anatomical registration or a conductor geometry.",
            "Connections and peripheral centre-lines are schematic; not reconstructed neurites.",
            "All graph nodes are calculated and drawn; connections use display LOD only.",
        ],
    }
    return arrays, metadata
