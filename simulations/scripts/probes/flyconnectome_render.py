"""Diagnose native MeshParty headless capture with unchanged exported geometry."""

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(os.environ.get("ASPA_FLYCONNECTOME_REVIEW", "/work/review-exports"))
ORIGINAL = Path("/work/exports")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pixels(path):
    image = np.asarray(Image.open(path).convert("RGB"))
    red, green, blue = [image[:, :, i].astype(float) for i in range(3)]
    nr = int(((red > 1.4 * green) & (red > 1.4 * blue) & (red > 30)).sum())
    nb = int(((blue > 1.4 * green) & (blue > 1.4 * red) & (blue > 30)).sum())
    return {
        "width": image.shape[1],
        "height": image.shape[0],
        "red_pixels": nr,
        "blue_pixels": nb,
        "expected_coloured_geometry_visible": nr > 10 and nb > 10,
        "sha256": sha(path),
    }


def configure(mode):
    import vtk
    from meshparty import trimesh_vtk

    setup = trimesh_vtk._setup_renderer
    capture = vtk.vtkWindowToImageFilter
    trace = {
        "mode": mode,
        "meshparty_source_sha256": sha(Path(trimesh_vtk.__file__)),
        "offscreen_before_first_render": mode in {"offscreen", "both"},
        "read_back_buffer": mode in {"backbuffer", "both"},
        "disable_fxaa": mode.startswith("nofxaa"),
    }

    def explicit_setup(*args, **kwargs):
        renderer, window, interactor = setup(*args, **kwargs)
        trace["window_class"] = window.GetClassName()
        if trace["disable_fxaa"]:
            renderer.UseFXAAOff()
        if mode.endswith(("-offscreen", "-both")):
            trace["offscreen_before_first_render"] = True
        if trace["offscreen_before_first_render"]:
            window.SetOffScreenRendering(1)
        return renderer, window, interactor

    def explicit_capture():
        value = capture()
        value.ReadFrontBufferOff()
        return value

    trimesh_vtk._setup_renderer = explicit_setup
    if mode.endswith("-both"):
        trace["read_back_buffer"] = True
    if trace["read_back_buffer"]:
        vtk.vtkWindowToImageFilter = explicit_capture
    return trimesh_vtk, trace


def mesh(path):
    from meshparty import trimesh_io

    with np.load(path) as data:
        return trimesh_io.Mesh(vertices=data["vertices"], faces=data["faces"])


def fixture(mode):
    import trimesh
    from meshparty import trimesh_io

    OUT.mkdir(exist_ok=True)

    native, trace = configure(mode)
    first = trimesh.creation.icosphere(subdivisions=1, radius=0.8)
    second = first.copy()
    first.vertices[:, 0] -= 1
    second.vertices[:, 0] += 1
    first = trimesh_io.Mesh(vertices=first.vertices, faces=first.faces)
    second = trimesh_io.Mesh(vertices=second.vertices, faces=second.faces)
    actors = [
        native.mesh_actor(first, color=(0.8, 0.1, 0.2), opacity=1),
        native.mesh_actor(second, color=(0.1, 0.2, 0.8), opacity=1),
    ]
    target = OUT / ("fixture-" + mode + ".png")
    native.render_actors(
        actors,
        do_save=True,
        filename=str(target),
        scale=4,
        video_width=600,
        video_height=400,
    )
    trace.update(pixels(target))
    trace["scope"] = "artificial render-only fixture; no biological claim"
    (OUT / ("fixture-" + mode + ".json")).write_text(json.dumps(trace, indent=2) + "\n")


def full(mode, suffix=""):
    OUT.mkdir(exist_ok=True)
    native, trace = configure(mode)
    info = json.loads((ORIGINAL / "meshes.json").read_text())
    for item in info["meshes"]:
        assert sha(ORIGINAL / item["file"]) == item["sha256"]
    items = [x for x in info["meshes"] if x["file"].startswith("neuron-v783-")]
    actors = [
        native.mesh_actor(mesh(ORIGINAL / item["file"]), color=color, opacity=1)
        for item, color in zip(items, [(0.8, 0.1, 0.2), (0.1, 0.2, 0.8)], strict=True)
    ]
    brain = mesh(ORIGINAL / "whole-neuropil-v3.npz")
    background = native.mesh_actor(brain, face_colors=(1.0, 1.0, 1.0), opacity=0.1)
    document = json.loads(
        Path("/work/source/Renderings with MeshParty.ipynb").read_text()
    )
    code = "".join(document["cells"][4]["source"])
    namespace = {"trimesh_vtk": native}
    exec(compile(ast.parse(code), "author-camera-cell-4", "exec"), namespace)  # noqa: S102 -- exact pinned camera cell
    outputs = []
    for label, selected in [
        ("neurons", actors),
        ("neurons-with-neuropil", actors + [background]),
    ]:
        target = OUT / ("headless-" + label + suffix + ".png")
        native.render_actors(
            selected,
            camera=namespace["front_camera"],
            do_save=True,
            scale=4,
            filename=str(target),
        )
        record = {"file": target.name, **pixels(target)}
        outputs.append(record)
    trace.update(
        scope="native MeshParty renderer, original full meshes/camera/actors/scale; capture adaptation only",
        outputs=outputs,
    )
    (OUT / ("full-render" + suffix + ".json")).write_text(
        json.dumps(trace, indent=2) + "\n"
    )
    assert all(x["expected_coloured_geometry_visible"] for x in outputs)


def driver():
    OUT.mkdir(exist_ok=True)
    trials = []
    for mode in [
        "native",
        "offscreen",
        "backbuffer",
        "both",
        "nofxaa",
        "nofxaa-offscreen",
        "nofxaa-both",
    ]:
        log = OUT / ("fixture-" + mode + ".log")
        with log.open("w") as stream:
            result = subprocess.run(
                [sys.executable, "-u", __file__, "fixture", mode],
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        receipt = OUT / ("fixture-" + mode + ".json")
        trials.append(
            {
                "mode": mode,
                "exit_code": result.returncode,
                "pixels": json.loads(receipt.read_text()) if receipt.exists() else None,
            }
        )
    original = {p.name: pixels(p) for p in ORIGINAL.glob("native-neuron-render*.png")}
    selected = next(
        (
            x["mode"]
            for x in trials
            if x["exit_code"] == 0 and x["pixels"]["expected_coloured_geometry_visible"]
        ),
        None,
    )
    report = {
        "original_recorded_images": original,
        "fixture_trials": trials,
        "selected_mode": selected,
    }
    (OUT / "render-diagnosis.json").write_text(json.dumps(report, indent=2) + "\n")
    assert selected is not None, (
        "No native capture mode produced visible fixture geometry"
    )
    for suffix in ["", "-repeat"]:
        subprocess.run(
            [sys.executable, "-u", __file__, "full", selected, suffix], check=True
        )
    first = json.loads((OUT / "full-render.json").read_text())
    second = json.loads((OUT / "full-render-repeat.json").read_text())
    equal = [
        a["sha256"] == b["sha256"]
        for a, b in zip(first["outputs"], second["outputs"], strict=True)
    ]
    report.update(
        status="passed", repeat_equal=all(equal), full_outputs=first["outputs"]
    )
    (OUT / "render-diagnosis.json").write_text(json.dumps(report, indent=2) + "\n")
    assert all(equal), "Visual repeat differed; inspect both complete retained images"


if __name__ == "__main__":
    if sys.argv[1] == "fixture":
        fixture(sys.argv[2])
    elif sys.argv[1] == "full":
        full(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    else:
        driver()
