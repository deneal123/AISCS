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

The source FlyBody external anatomy was constructed from microscopy of an adult
female, according to [Janelia's description](https://www.janelia.org/news/artificial-intelligence-brings-a-virtual-fly-to-life).
The MaleCNS connectome is a different, adult male specimen. Their display overlay
is not a measured anatomical registration or a basis for physical electrode
placement; sex and individual differences remain unresolved.

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

## Source joint hierarchy

`rig.json` exports all 68 source body frames (67 bodies plus the world reference),
102 hinges and the body binding of all
85 baked meshes. The free body root remains at the registered rest pose. Angles
are radians, positions millimetres; matrices are row-major 4×4 transforms of
column vectors. The mesh and its registration are unchanged.

The exporter reads the same pinned XML and MuJoCo 3.3.7. Its SHA-256 is
`35541d5312f71e7c96156c345cd90918867513a2b3dafbb07b8684ee59b6f4dc`.
The canonical UTF-8/LF rig is 56,739 bytes, SHA-256
`848804eae147fbfd30af36f1c5f406446b3850bda7f13f4ed81783f7c4cbd5ea`.
This derivative retains the Apache-2.0 source-model license.

```powershell
.work/flybody-export/.venv/Scripts/python.exe frontend/scripts/export-simulator-rig.py --source-xml .work/flybody-export/input/fruitfly.xml --asset-root frontend/public/assets/simulator/flybody --output frontend/public/assets/simulator/flybody/rig.json --references frontend/tests/fixtures/simulator/flybody-kinematics-reference.json
```

`flyKinematics` computes the complete forward hierarchy and per-part transforms
relative to the baked rest pose. Independent MuJoCo fixtures cover the neutral
pose, three head axes, and simultaneous changes of every hinge for seeds 1–3.
Every body frame and joint anchor is checked. The numerical tolerance is a
software comparison, not an anatomical accuracy claim. A repeat export in the
same pinned environment is byte-identical; cross-OS floating-point identity has
not been claimed.

The scene's **Суставы** control displays this source structure and follows the
existing conditional leg poses. Eye meshes belong to the head; no independent
eye joint is introduced. A complete motor/muscle controller, joint loads and
proprioceptive feedback remain separate requirements.
