# FlyBody: body geometry used by SIM-003

The scene uses the FlyBody body model distributed in MuJoCo Menagerie under
Apache-2.0. Its model XML is byte-for-byte identical to SIM-003's pinned XML.
The 85 indexed OBJ assets were read from SIM-003's Git objects at
`fdbbd866b203a709a164970b0a8996108edd57a5`; the SIM worktree was not changed.
The upstream model and license were checked at Menagerie commit
`f3b6013629c7b94f8ee93fd977b161fa8350f9bc`.

- Primary model: https://github.com/google-deepmind/mujoco_menagerie/tree/f3b6013629c7b94f8ee93fd977b161fa8350f9bc/flybody
- Original authors: Google DeepMind and HHMI Janelia; see the primary README
  and its citation of Vaxenburg et al., DOI `10.1101/2024.03.11.584515`.
- License: [Apache-2.0](LICENSE-FlyBody.txt).
- File provenance and SHA-256: [provenance.json](provenance.json).
- Registered visual embedding: [registration.json](registration.json).

`scene.json` describes 85 visual meshes and 272550 triangles. `scene.bin` is a
little-endian float32 position/normal and uint32 index buffer (6586128 bytes).
Normals, colors and source triangle order are retained. MuJoCo 3.3.7 evaluates
the neutral body pose with the source's six passive wing spring resting angles
once during export; centimetres are converted to millimetres.
This is a derivative export, not the original OBJ distribution. Browser loading
verifies both the metadata hash and the binary hash before displaying geometry.

The 102 hinge degrees of freedom belong to the source body model. This scene
currently moves six leg roots in response to recorded neural events. It does
not import a locomotion policy or establish biologically valid motor behavior.
The thorax, neural sources and physical recording frame remain static. The
local neural chain is author-defined; embedding it in FlyBody does not make it
a reconstructed fly connectome. Old FlyGym registrations remain available for
replaying older records without rewriting their provenance.

Re-export from the superproject root with an isolated environment:

```powershell
uv venv .work/flybody-export/.venv --python 3.13
uv pip install --python .work/flybody-export/.venv/Scripts/python.exe mujoco==3.3.7 numpy==2.5.4
.work/flybody-export/.venv/Scripts/python.exe frontend/scripts/export-simulator-flybody.py --repo simulations/sidecars/cnqso--infinite-sugar --out frontend/public/assets/simulator/flybody --work .work/flybody-export/input
```

Copy the generated registration to `generator/service/domain/flybody-scene-context.json`
only when deliberately publishing a new registered asset. Rebuild the generator
and run its contract tests before switching the running catalog. Never edit an
existing run's registration to match a newer visual asset.
