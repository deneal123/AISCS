"""Offline FANC coordinate operations; fixtures are not reconstructed neurons."""

import builtins
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path

import fanc
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import navis
import networkx as nx
import numpy as np
from mpl_toolkits.mplot3d.art3d import Line3DCollection

OUT = (Path("/work") / os.environ.get("ASPA_FANC_EXPORT_DIR", "export")).resolve()
if not OUT.is_relative_to(Path("/work")) or OUT == Path("/work"):
    raise ValueError("FANC export must remain inside its run")
OUT.mkdir(exist_ok=True)


def morphology():
    work = Path("/work")
    manifest = json.loads((work / "fanc-inputs.json").read_text())
    fig = plt.figure(figsize=(13, 6), layout="constrained")
    stats = []
    for i, item in enumerate(manifest["inputs"]):
        path = work / item["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Pinned FANC SWC changed")
        neuron = navis.read_swc(str(path))
        nodes = neuron.nodes
        xyz = nodes[["x", "y", "z"]].to_numpy(dtype=float)
        assert np.isfinite(xyz).all() and not nodes.node_id.duplicated().any()
        assert nx.is_directed_acyclic_graph(neuron.graph)
        lookup = nodes.set_index("node_id")
        connected = nodes[nodes.parent_id >= 0]
        assert connected.parent_id.isin(lookup.index).all()
        segments = np.stack(
            [
                connected[["x", "y", "z"]].to_numpy(),
                lookup.loc[connected.parent_id, ["x", "y", "z"]].to_numpy(),
            ],
            axis=1,
        )
        ax = fig.add_subplot(1, 2, i + 1, projection="3d")
        ax.add_collection3d(
            Line3DCollection(segments, linewidths=0.3, colors="#245b80")
        )
        lower, upper = xyz.min(axis=0), xyz.max(axis=0)
        ax.set(
            xlim=(lower[0], upper[0]),
            ylim=(lower[1], upper[1]),
            zlim=(lower[2], upper[2]),
            xlabel="X (stored units)",
            ylabel="Y (stored units)",
            zlabel="Z (stored units)",
        )
        ax.set_box_aspect(np.maximum(upper - lower, 1))
        ax.set_axis_off()
        kind = "High-resolution SWC" if "high-res" in path.name else "PCG SWC"
        ax.set_title(f"{kind}: {len(nodes):,} nodes")
        stats.append(
            {
                "file": item["file"],
                "nodes": len(nodes),
                "roots": int((nodes.parent_id < 0).sum()),
                "min": lower.tolist(),
                "max": upper.tolist(),
                "units": "as stored; correspondence between exports not established",
                "acyclic": True,
            }
        )
    fig.suptitle(
        "FANC: authored exports of neuron 648518346486614449\nShape previews at independent scales; physical unit correspondence not established"
    )
    for ext in ("png", "svg"):
        fig.savefig(OUT / ("authored-morphology." + ext), dpi=160)
    plt.close(fig)
    (OUT / "morphology-checks.json").write_text(
        json.dumps(
            {
                "inputs": stats,
                "source_date": "High-resolution header: 2023-07-31; example notebook references July 2023",
                "materialization": "not established for these files",
            },
            indent=2,
        )
        + "\n"
    )


def check(seed, suffix):
    rng = np.random.default_rng(seed)
    links = rng.uniform(1000, 50000, (64, 6)).astype(np.float64)
    original = links.copy()
    tools = fanc.synaptic_links
    assert np.array_equal(
        tools.flip_xyz_zyx_convention(
            tools.flip_xyz_zyx_convention(links, inplace=False), inplace=False
        ),
        links,
    )
    assert np.array_equal(
        tools.flip_pre_post_order(
            tools.flip_pre_post_order(links, inplace=False), inplace=False
        ),
        links,
    )
    voxel_size = (4.3, 4.3, 45.0)
    scaled = tools.upscale(links, voxel_size, inplace=False)
    restored = tools.downscale(scaled, voxel_size, inplace=False)
    assert np.allclose(restored, links, rtol=1e-14, atol=1e-10)
    assert np.array_equal(links, original)
    # The native .npy format is post/pre, zyx, nanometers: encode explicitly.
    raw = tools.flip_xyz_zyx_convention(
        tools.flip_pre_post_order(links, inplace=False), inplace=False
    )
    source = OUT / ("links-" + suffix + ".npy")
    np.save(source, raw)
    loaded = tools.load(str(source), units="nm", verbose=False)
    assert np.array_equal(loaded, links)
    voxels = tools.load(
        str(source), units="voxels", voxel_size=voxel_size, verbose=False
    )
    assert np.allclose(voxels, tools.downscale(links, voxel_size, inplace=False))
    captured = io.StringIO()
    answer = builtins.input
    try:
        builtins.input = lambda *args: "n"  # Do not access the host clipboard.
        with contextlib.redirect_stdout(captured):
            tools.to_ng_annotations(links, input_units=voxel_size)
    finally:
        builtins.input = answer
    annotations, _ = json.JSONDecoder().raw_decode(captured.getvalue().lstrip())
    actual = np.asarray([x["pointA"] + x["pointB"] for x in annotations])
    assert actual.shape == (64, 6) and np.isfinite(actual).all()
    assert np.allclose(actual, voxels)
    assert len({x["id"] for x in annotations}) == 64
    (OUT / ("annotations-" + suffix + ".json")).write_text(
        json.dumps(annotations, indent=2) + "\n"
    )
    np.savetxt(
        OUT / ("coordinates-" + suffix + ".csv"),
        voxels,
        delimiter=",",
        header="pre_x,pre_y,pre_z,post_x,post_y,post_z",
        comments="",
    )
    return voxels, annotations


def main():
    morphology()
    runs = [
        check(seed, suffix)
        for seed, suffix in ((1, "1"), (2, "2"), (3, "3"), (1, "1-repeat"))
    ]
    assert np.array_equal(runs[0][0], runs[3][0])
    assert not np.array_equal(runs[0][0], runs[1][0])
    for alias, expected in (
        ("FEMALE", "JRCVNC2018F"),
        ("MALE", "JRCVNC2018M"),
        ("UNISEX", "JRCVNC2018U"),
    ):
        assert fanc.template_spaces.to_navis_name(alias) == expected
    assert fanc.annotations.is_valid_annotation(
        "primary class: motor neuron", table_name="neuron_information"
    )
    assert not fanc.annotations.is_valid_annotation(
        "motor neuron: primary class",
        table_name="neuron_information",
        raise_errors=False,
    )
    values = runs[0][0]
    fig, ax = plt.subplots(figsize=(9, 5.5), layout="constrained")
    for row in values[:32]:
        ax.plot([row[0], row[3]], [row[1], row[4]], color="#7c9eae", alpha=0.6, lw=0.7)
    ax.scatter(values[:32, 0], values[:32, 1], c="#235f8c", label="pre points")
    ax.scatter(
        values[:32, 3], values[:32, 4], c="#b75d3b", marker="x", label="post points"
    )
    ax.set(
        xlabel="x (voxels, explicit 4.3 nm scale)",
        ylabel="y (voxels, explicit 4.3 nm scale)",
        title="FANC link I/O: numerical fixture, not anatomical neuron positions",
    )
    ax.legend()
    for ext in ("png", "svg"):
        fig.savefig(OUT / ("coordinate-io." + ext), dpi=160)
    plt.close(fig)
    receipt = {
        "scope": "Two pinned authored SWC exports read/rendered; separate offline numerical coordinate fixtures. No fresh reconstruction or full connectome downloaded.",
        "seeds": [1, 2, 3, 1],
        "repeat_seed_equal": True,
        "finite_and_shape_checks": True,
        "units": "nanometers and voxels; explicit (4.3,4.3,45) nm voxel size",
        "annotation_ids_repeat": runs[0][1] == runs[3][1],
        "note": "Native annotation IDs use secrets.token_hex; numpy seeds do not make these IDs deterministic. Coordinates repeat exactly.",
        "coordinate_sha256": hashlib.sha256(
            (OUT / "coordinates-1.csv").read_bytes()
        ).hexdigest(),
        "live_data": "Unmodified upstream tests separately exercise protected services; no credentials supplied",
    }
    (OUT / "functional-checks.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
