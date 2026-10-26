"""Check saved arrays independently of cloud access and make an atlas preview."""

import hashlib
import json
import os
from pathlib import Path

import matplotlib
import ncollpyde
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

ORIGINAL = Path("/work/exports")
OUT = Path(os.environ.get("ASPA_FLYCONNECTOME_REVIEW", "/work/review-exports"))
OUT.mkdir(exist_ok=True)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    volume = json.loads((ORIGINAL / "volumes.json").read_text())
    seg = np.load(ORIGINAL / "segmentation-v630.npy")
    em = np.load(ORIGINAL / "em-fafb-v14.npy")
    assert sha(ORIGINAL / "segmentation-v630.npy") == volume["segmentation"]["sha256"]
    assert sha(ORIGINAL / "em-fafb-v14.npy") == volume["em"]["sha256"]
    assert seg.dtype == np.uint64 and em.dtype == np.uint8
    assert int(np.unique(seg).size) == volume["segmentation"]["unique_ids"]
    assert np.isfinite(seg).all() and np.isfinite(em).all()
    seg_resolution = np.array(volume["segmentation"]["resolution_nm"])
    em_resolution = np.array(volume["em"]["resolution_nm"])
    seg_start = np.array([32500, 12500, 2500]) * seg_resolution
    em_start = np.array([65000, 25000, 2500]) * em_resolution
    np.testing.assert_array_equal(seg_start, em_start)
    np.testing.assert_array_equal(
        np.array(seg.shape[:3]) * seg_resolution, np.array(em.shape[:3]) * em_resolution
    )
    extent = (
        np.array(
            [
                seg_start[0],
                seg_start[0] + seg.shape[0] * seg_resolution[0],
                seg_start[1],
                seg_start[1] + seg.shape[1] * seg_resolution[1],
            ]
        )
        / 1000
    )
    # This illustration uses exact label identity for lookup; colour collisions
    # remain possible and never alter the uint64 array stored separately.
    ids, inverse = np.unique(seg[:, :, 0, 0], return_inverse=True)
    colours = np.random.default_rng(1).uniform(0.15, 0.95, (len(ids), 3))
    display = colours[inverse].reshape((*seg.shape[:2], 3)).transpose(1, 0, 2)
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), layout="constrained")
    axes[0].imshow(em[:, :, 0, 0].T, cmap="gray", origin="lower", extent=extent)
    axes[1].imshow(display, origin="lower", extent=extent)
    for ax, title in zip(
        axes, ["FAFB v14 electron microscopy", "FlyWire v630 segmentation"], strict=True
    ):
        ax.set(title=title, xlabel="Source X (µm)", ylabel="Source Y (µm)")
    fig.suptitle(
        "Same specified 8 × 8 µm field at Z = 100 µm\nIndependent read of saved arrays; registration accuracy is not evaluated here"
    )
    fig.savefig(OUT / "registered-cutout-preview.png", dpi=170)
    plt.close(fig)
    del seg, em

    neuropils = json.loads((ORIGINAL / "neuropils.json").read_text())
    neurons = json.loads((ORIGINAL / "meshes.json").read_text())
    points = np.array(neuropils["author_example_locations"])
    classified = [[], []]
    records = []
    fig = plt.figure(figsize=(12, 7), layout="constrained")
    ax = fig.add_subplot(projection="3d", computed_zorder=False)
    lower, upper = [], []
    total_vertices = total_faces = 0
    for item in neuropils["meshes"] + neurons["meshes"]:
        path = ORIGINAL / item["file"]
        assert sha(path) == item["sha256"]
        with np.load(path) as arrays:
            vertices, faces = arrays["vertices"], arrays["faces"]
        assert vertices.shape == (item["vertices"], 3) and faces.shape == (
            item["faces"],
            3,
        )
        assert np.isfinite(vertices).all() and np.issubdtype(faces.dtype, np.integer)
        assert faces.min() >= 0 and faces.max() < len(vertices)
        total_vertices += len(vertices)
        total_faces += len(faces)
        record = {
            "file": item["file"],
            "sha256": item["sha256"],
            "vertices": len(vertices),
            "faces": len(faces),
        }
        if "root_id" in item:
            record["root_id_string"] = str(item["root_id"])
        if "name" in item:
            body = ncollpyde.Volume(vertices, faces, n_rays=3)
            result = body.contains(points).tolist()
            assert result == neuropils["contains"][item["name"]]
            del body
            for i, inside in enumerate(result):
                if inside:
                    classified[i].append(item["name"])
            xyz = vertices / 1000
            lower.append(xyz.min(axis=0))
            upper.append(xyz.max(axis=0))
            colour = plt.get_cmap("tab20")(item["id"] % 20)
            ax.add_collection3d(
                Poly3DCollection(
                    xyz[faces],
                    facecolors=colour,
                    edgecolors="none",
                    alpha=0.22,
                    rasterized=True,
                    zorder=1,
                )
            )
        records.append(record)
    assert len(records) == 83
    low, high = np.min(lower, axis=0), np.max(upper, axis=0)
    for setter, lo, hi in zip(
        [ax.set_xlim, ax.set_ylim, ax.set_zlim], low, high, strict=True
    ):
        setter(lo, hi)
    ax.scatter(
        *((points / 1000).T), c=["black", "red"], s=45, depthshade=False, zorder=20
    )
    for i, point in enumerate(points / 1000):
        ax.text(
            *point,
            f"  P{i + 1}: {', '.join(classified[i])}",
            color="black" if i == 0 else "red",
            fontsize=11,
            zorder=30,
        )
    ax.set(
        xlabel="Source X (µm)",
        ylabel="Source Y (µm)",
        zlabel="Source Z (µm)",
        title="78 published neuropil surfaces and the two author example points\nColours distinguish meshes; they do not label function or nociception",
    )
    ax.set_box_aspect(high - low)
    ax.view_init(elev=18, azim=-88)
    fig.savefig(OUT / "neuropil-atlas-preview.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    info = {
        "status": "passed",
        "reader_does_not_import_cloudvolume_or_project_code": True,
        "verified_mesh_exports": len(records),
        "vertices_checked": total_vertices,
        "faces_checked": total_faces,
        "segmentation_unique_ids": volume["segmentation"]["unique_ids"],
        "same_specified_physical_roi_nm": {
            "origin": seg_start.tolist(),
            "size": (seg_resolution * [500, 500, 10]).tolist(),
        },
        "point_membership_recomputed": classified,
        "mesh_exports": records,
        "scope": "independent format/hash/coordinate checks and anatomical previews; no biological validation",
    }
    (OUT / "reader-check.json").write_text(json.dumps(info, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in info.items() if key != "mesh_exports"}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
