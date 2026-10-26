"""Separate VTK-driver rendering from MeshParty actor and capture behavior."""

import json
import os
import subprocess
import sys
from pathlib import Path

import vtk
from flyconnectome_render import pixels

OUT = Path(os.environ.get("ASPA_FLYCONNECTOME_REVIEW", "/work/review-exports"))


def worker(actor_kind, scale):
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(1, 1, 1)
    window = vtk.vtkRenderWindow()
    window.SetSize(600, 400)
    window.SetOffScreenRendering(1)
    window.AddRenderer(renderer)
    sources = []
    for x, colour in [(-1, (0.8, 0.1, 0.2)), (1, (0.1, 0.2, 0.8))]:
        if actor_kind == "vtk":
            source = vtk.vtkSphereSource()
            source.SetCenter(x, 0, 0)
            source.SetRadius(0.8)
            source.SetPhiResolution(24)
            source.SetThetaResolution(32)
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(source.GetOutputPort())
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*colour)
            sources.append(source)
        else:
            import trimesh
            from meshparty import trimesh_io, trimesh_vtk

            geometry = trimesh.creation.icosphere(subdivisions=1, radius=0.8)
            geometry.vertices[:, 0] += x
            geometry = trimesh_io.Mesh(vertices=geometry.vertices, faces=geometry.faces)
            actor = trimesh_vtk.mesh_actor(geometry, color=colour, opacity=1)
        renderer.AddActor(actor)
    renderer.ResetCamera()
    window.Render()
    target = OUT / f"direct-{actor_kind}-scale{scale}.png"
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.ReadFrontBufferOff()
    capture.SetInputBufferTypeToRGB()
    capture.SetScale(scale)
    capture.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(target))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    result = {
        "actor": actor_kind,
        "scale": scale,
        "window_class": window.GetClassName(),
        "supports_opengl": bool(window.SupportsOpenGL()),
        "capabilities": window.ReportCapabilities(),
        **pixels(target),
    }
    (OUT / f"direct-{actor_kind}-scale{scale}.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    window.Finalize()


def main():
    cases = []
    for kind in ["vtk", "meshparty"]:
        for scale in [1, 4]:
            log = OUT / f"direct-{kind}-scale{scale}.log"
            with log.open("w") as stream:
                result = subprocess.run(
                    [sys.executable, "-u", __file__, kind, str(scale)],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            path = OUT / f"direct-{kind}-scale{scale}.json"
            cases.append(
                {
                    "actor": kind,
                    "scale": scale,
                    "exit_code": result.returncode,
                    "result": json.loads(path.read_text()) if path.exists() else None,
                }
            )
    (OUT / "direct-vtk-check.json").write_text(
        json.dumps({"cases": cases}, indent=2) + "\n"
    )


if __name__ == "__main__":
    if len(sys.argv) > 2:
        worker(sys.argv[1], int(sys.argv[2]))
    else:
        main()
