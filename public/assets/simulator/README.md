# Fly geometry

`fly.json` is exported from the simplified NeuroMechFly STL geometry and rigging
in FlyGym, SIM-020, commit `38c8ec61034cd59bc5ba0de20688d4a3c0000d60`.
Source: https://github.com/NeLy-EPFL/flygym . License: Apache-2.0, full text in
`LICENSE-FlyGym.txt`. File-level provenance and hashes are in `provenance.json`.

The local exporter `scripts/export-simulator-fly.py` assembles 69 parts in the
neutral pose, mirrors right-side parts, and expresses geometry in millimetres.
The simulator renderer recolors body, eyes and wings. No source SIM files are
modified. The mesh is visual context, not evidence of matched neuronal morphology.
