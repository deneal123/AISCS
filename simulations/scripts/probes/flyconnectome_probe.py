"""Run pinned FlyWire tutorial operations, keeping API access outcomes separate."""

import ast
import hashlib
import importlib.metadata
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SOURCE = Path("/work/source")
OUT = Path(os.environ.get("ASPA_FLYCONNECTOME_EXPORT", "/work/exports")).resolve()
if OUT == Path("/work") or not OUT.is_relative_to(Path("/work")):
    raise ValueError("FlyConnectome exports must stay inside their owned run")
OUT.mkdir(exist_ok=True)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")
    print(name, json.dumps(value)[:900], flush=True)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cell(notebook, index):
    document = json.loads((SOURCE / notebook).read_text())
    return "".join(document["cells"][index]["source"])


def definition(notebook, index, name, namespace):
    tree = ast.parse(cell(notebook, index))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(nodes) == 1
    exec(  # noqa: S102 -- execute one exact function from the pinned notebook
        compile(
            ast.Module(body=nodes, type_ignores=[]),
            notebook + f"#/cells/{index}",
            "exec",
        ),
        namespace,
    )
    return namespace[name]


def literal(notebook, index, name):
    tree = ast.parse(cell(notebook, index))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError("Missing author literal " + name)


def software():
    remap = definition(
        "Segmentation and Mesh Access.ipynb", 16, "remap_seg", {"np": np}
    )
    fixture = np.array(
        [[0, 720575940631693610], [2**63 + 1, 720575940631693610]], dtype=np.uint64
    )
    original = fixture.copy()
    arrays = [remap(fixture, seed=seed) for seed in [1, 2, 3, 1]]
    assert np.array_equal(arrays[0], arrays[-1])
    assert np.array_equal(fixture, original)
    assert all(a.shape == fixture.shape and np.isfinite(a).all() for a in arrays)
    assert all(a[0, 1] == a[1, 1] for a in arrays)
    save(
        "software.json",
        {
            "passed": True,
            "scope": "own artificial uint64-label fixture calling the unchanged notebook remap_seg function",
            "repeat_equal": True,
            "exact_original_ids_preserved": True,
            "display_mapping_is_not_invertible_or_an_ID_export": True,
        },
    )


def smoke():
    import caveclient
    import cloudvolume
    import navis
    import ncollpyde
    from meshparty import trimesh_vtk

    save(
        "libraries.json",
        {
            "versions": {
                name: importlib.metadata.version(name)
                for name in [
                    "caveclient",
                    "cloud-volume",
                    "meshparty",
                    "navis",
                    "ncollpyde",
                    "numpy",
                    "pandas",
                    "vtk",
                ]
            },
            "render_signature": str(inspect.signature(trimesh_vtk.render_actors)),
            "cave_signature": str(inspect.signature(caveclient.CAVEclient)),
            "cloudvolume_signature": str(inspect.signature(cloudvolume.CloudVolume)),
            "navis_import": bool(navis),
            "ncollpyde_import": bool(ncollpyde),
        },
    )


def volume(path, mip=0):
    from cloudvolume import CloudVolume

    # Strict missing-chunk behavior: blank replacement must not pass as real data.
    cv = CloudVolume(
        path,
        use_https=True,
        fill_missing=False,
        mip=mip,
        cache=False,
        parallel=1,
        progress=False,
    )
    names = {
        "precomputed://gs://flywire_v141_m630": "segmentation-v630",
        "precomputed://gs://flywire_v141_m783": "segmentation-v783",
        "precomputed://gs://flywire_neuropil_meshes/neuropils/neuropil_mesh_v141_v5": "neuropil-v5",
        "precomputed://gs://flywire_neuropil_meshes/whole_neuropil/brain_mesh_v3": "whole-neuropil-v3",
        "precomputed://https://bossdb-open-data.s3.amazonaws.com/flywire/fafbv14": "em-fafb-v14",
    }
    expected = json.loads(
        (Path("/work/inputs") / (names[path] + "-info.json")).read_text()
    )
    if cv.info != expected:
        raise ValueError(
            "Live volume metadata differs from the checked primary snapshot"
        )
    return cv


def volumes():
    notebook = "Segmentation and Mesh Access.ipynb"
    seg_path, em_path = (
        literal(notebook, 6, "seg_path"),
        literal(notebook, 18, "em_path"),
    )
    seg, em = volume(seg_path), volume(em_path, mip=1)
    raw_seg = np.asarray(seg[32500:33000, 12500:13000, 2500:2510])
    raw_em = np.asarray(em[65000:66000, 25000:26000, 2500:2510])
    assert raw_seg.shape == (500, 500, 10, 1) and raw_seg.dtype == np.uint64
    assert raw_em.shape == (1000, 1000, 10, 1)
    assert np.isfinite(raw_em).all() and np.isfinite(raw_seg).all()
    assert np.unique(raw_seg).size > 1 and raw_em.max() > raw_em.min()
    np.save(OUT / "segmentation-v630.npy", raw_seg)
    np.save(OUT / "em-fafb-v14.npy", raw_em)
    np.testing.assert_array_equal(
        raw_seg, np.asarray(seg[32500:33000, 12500:13000, 2500:2510])
    )
    remap = definition(notebook, 16, "remap_seg", {"np": np})
    mapped = [remap(raw_seg[:, :, 0, 0], seed=seed) for seed in [1, 2, 3, 1]]
    np.testing.assert_array_equal(mapped[0], mapped[-1])
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), layout="constrained")
    axes[0].imshow(raw_em[:, :, 0, 0].T, cmap="gray", origin="lower")
    axes[1].imshow(mapped[0].T, cmap="nipy_spectral", origin="lower")
    for ax, title in zip(
        axes,
        [
            "FAFB v14 EM — author mip-1 cutout",
            "FlyWire v630 segmentation — display colours",
        ],
        strict=True,
    ):
        ax.set(title=title, xlabel="Cutout X (voxels)", ylabel="Cutout Y (voxels)")
    fig.suptitle(
        "Actual public volumes at the author's coordinates\nColour mapping is illustrative; original uint64 IDs are stored separately"
    )
    fig.savefig(OUT / "public-em-and-segmentation.png", dpi=170)
    plt.close(fig)
    save(
        "volumes.json",
        {
            "status": "passed",
            "scope": "two registered tutorial cutouts, not a whole-volume reconstruction or simulation",
            "segmentation": {
                "path": seg_path,
                "shape": list(raw_seg.shape),
                "dtype": str(raw_seg.dtype),
                "resolution_nm": np.asarray(seg.resolution).tolist(),
                "unique_ids": int(np.unique(raw_seg).size),
                "sha256": sha(OUT / "segmentation-v630.npy"),
            },
            "em": {
                "path": em_path,
                "shape": list(raw_em.shape),
                "dtype": str(raw_em.dtype),
                "resolution_nm": np.asarray(em.resolution).tolist(),
                "sha256": sha(OUT / "em-fafb-v14.npy"),
            },
            "repeat_equal": True,
            "remote_segmentation_second_read_exact": True,
            "no_missing_chunk_zero_fill": True,
        },
    )


def mesh_value(cv, identifier, **kwargs):
    value = cv.mesh.get(identifier, **kwargs)
    return value[identifier] if isinstance(value, dict) else value


def export_mesh(name, mesh):
    vertices, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    assert vertices.ndim == faces.ndim == 2 and vertices.shape[1] == faces.shape[1] == 3
    assert np.isfinite(vertices).all() and len(vertices) and len(faces)
    assert (
        np.issubdtype(faces.dtype, np.integer)
        and faces.min() >= 0
        and faces.max() < len(vertices)
    )
    target = OUT / (name + ".npz")
    np.savez_compressed(target, vertices=vertices, faces=faces)
    return {
        "file": target.name,
        "vertices": len(vertices),
        "faces": len(faces),
        "sha256": sha(target),
        "bounds": [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()],
    }


def neuropils():
    import ncollpyde

    notebook = "Neuropils and Point Lookups.ipynb"
    cv = volume(literal(notebook, 5, "np_path"))
    names = literal(notebook, 5, "mesh_map")
    points = np.array([[480420, 308060, 97520], [530968, 161116, 159440]])
    records, classification = [], {}
    for identifier, name in names.items():
        if int(identifier) >= 78:
            continue
        print("Neuropil", identifier, name, flush=True)
        mesh = mesh_value(cv, int(identifier))
        records.append(
            {
                "id": int(identifier),
                "name": name,
                **export_mesh("neuropil-" + name, mesh),
            }
        )
        body = ncollpyde.Volume(mesh.vertices, mesh.faces, n_rays=3)
        first, second = body.contains(points), body.contains(points)
        np.testing.assert_array_equal(first, second)
        classification[name] = first.tolist()
        del body, mesh
        save("neuropil-progress.json", {"completed": len(records), "total": 78})
    assert len(records) == 78
    save(
        "neuropils.json",
        {
            "status": "passed",
            "meshes": records,
            "author_example_locations": points.tolist(),
            "contains": classification,
            "repeat_equal": True,
            "scope": "author point-in-neuropil query; anatomical location is not a functional or nociceptive label",
        },
    )


def meshes():
    from flyconnectome_render import configure
    from meshparty import trimesh_io, trimesh_vtk

    _, render_configuration = configure("nofxaa")

    notebook = "Renderings with MeshParty.ipynb"
    seg_path = literal(notebook, 7, "seg_path")
    identifiers = literal(notebook, 8, "root_ids")
    cv = volume(seg_path)
    convert = definition(notebook, 6, "mp_mesh_from_cv", {"trimesh_io": trimesh_io})
    neurons = {identifier: convert(cv, identifier) for identifier in identifiers}
    records = [
        {"root_id": identifier, **export_mesh("neuron-v783-" + str(identifier), mesh)}
        for identifier, mesh in neurons.items()
    ]
    whole_path = literal(notebook, 10, "np_path")
    whole = convert(volume(whole_path), 1)
    records.append({"root_id": 1, **export_mesh("whole-neuropil-v3", whole)})
    namespace = {"trimesh_vtk": trimesh_vtk}
    exec(compile(cell(notebook, 4), notebook + "#/cells/4", "exec"), namespace)  # noqa: S102 -- pinned original camera cell
    camera = namespace["front_camera"]
    actors = [
        trimesh_vtk.mesh_actor(mesh, color=color, opacity=1)
        for mesh, color in zip(
            neurons.values(), [[0.8, 0.1, 0.2], [0.1, 0.2, 0.8]], strict=True
        )
    ]
    background = trimesh_vtk.mesh_actor(whole, face_colors=(1.0, 1.0, 1.0), opacity=0.1)
    for suffix, selected in [("", actors), ("-with-neuropil", actors + [background])]:
        trimesh_vtk.render_actors(
            selected,
            camera=camera,
            do_save=True,
            scale=4,
            filename=str(OUT / ("native-neuron-render" + suffix + ".png")),
        )
    # The segmentation tutorial also requests this exact v630 root at LOD 2.
    older = volume(literal("Segmentation and Mesh Access.ipynb", 6, "seg_path"))
    for label, kwargs in [("default", {}), ("lod2", {"lod": 2})]:
        old = mesh_value(older, 720575940631693610, **kwargs)
        records.append(
            {
                "root_id": 720575940631693610,
                "version": "v630",
                "lod": label,
                **export_mesh("neuron-v630-" + label, old),
            }
        )
    save(
        "meshes.json",
        {
            "status": "passed",
            "meshes": records,
            "rendering": "original camera, actors, scale=4 and do_save=True; explicit FXAA-off adaptation for the verified EGL capture failure",
            "render_configuration": render_configuration,
            "scope": "surface meshes only, no neural dynamics, synaptic reconstruction or CAP",
        },
    )
    from PIL import Image

    visible = []
    for path in sorted(OUT.glob("native-neuron-render*.png")):
        rgb = np.asarray(Image.open(path).convert("RGB")).astype(float)
        red, green, blue = [rgb[:, :, i] for i in range(3)]
        visible.append(
            {
                "file": path.name,
                "red_pixels": int(
                    ((red > 1.4 * green) & (red > 1.4 * blue) & (red > 30)).sum()
                ),
                "blue_pixels": int(
                    ((blue > 1.4 * green) & (blue > 1.4 * red) & (blue > 30)).sum()
                ),
            }
        )
    save("render-pixels.json", {"images": visible})
    if not visible or any(
        x["red_pixels"] <= 10 or x["blue_pixels"] <= 10 for x in visible
    ):
        raise RuntimeError(
            "Renderer exited successfully but did not show the expected coloured geometry"
        )


def cave():
    import caveclient

    records = []
    for attempt in [1, 2]:
        try:
            client = caveclient.CAVEclient("flywire_fafb_public", auth_token=None)
            versions = client.materialize.get_versions()
            tables = client.materialize.get_tables()
            sample = client.materialize.query_table(
                "hierarchical_neuron_annotations", limit=10
            )
            sample.to_csv(OUT / "cave-annotations-sample.csv", index=False)
            save(
                "cave.json",
                {
                    "status": "passed",
                    "attempts": records,
                    "versions": versions,
                    "tables": tables,
                    "sample_rows": len(sample),
                    "scope": "limited actual registered annotation query; not all tutorial queries",
                },
            )
            return
        except Exception as exc:  # noqa: BLE001 -- retain each upstream API failure, never declare it successful
            records.append(
                {
                    "attempt": attempt,
                    "exception": type(exc).__name__,
                    "error": str(exc)[:1600],
                }
            )
    save(
        "cave.json",
        {
            "status": "blocked",
            "attempts": records,
            "scope": "fresh isolated HOME; host tokens not read, no token creation or invalidation requested",
        },
    )
    raise RuntimeError(
        "CAVE query unavailable; inspect the retained failure without printing credentials"
    )


def full():
    records = []
    for name in ["volumes", "neuropils", "meshes", "cave"]:
        print("Tutorial scenario", name, flush=True)
        start = time.monotonic()
        log = OUT / (name + ".log")
        with log.open("w") as stream:
            result = subprocess.run(
                [sys.executable, "-u", __file__, name],
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=1800,
                check=False,
            )
        records.append(
            {
                "scenario": name,
                "status": "passed" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "wall_seconds": time.monotonic() - start,
                "log": log.name,
            }
        )
        save("tutorials.json", {"complete": False, "cases": records})
    save(
        "tutorials.json",
        {
            "complete": True,
            "cases": records,
            "scope": "pinned tutorial operations; no simulator or biological validation",
        },
    )
    if any(x["status"] != "passed" for x in records):
        raise RuntimeError(
            "Partial tutorial reproduction; failed access is not filled with fabricated data"
        )


if __name__ == "__main__":
    {
        "software": software,
        "smoke": smoke,
        "volumes": volumes,
        "neuropils": neuropils,
        "meshes": meshes,
        "cave": cave,
        "full": full,
    }[sys.argv[1]]()
