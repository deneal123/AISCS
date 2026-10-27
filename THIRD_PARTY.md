# Third-party components

The project's own code is MIT. That license does not replace dependency or dataset
licenses. Installed distributions retain their license files in the Docker image.

| Component | Pinned version / source | Use and license |
|---|---|---|
| Fly Arena | `12f48c702ed170b5bdc4643afa7ce65e952b353d` | Two unchanged LIF functions in `service/infrastructure/connectome/kernel.py`, and unchanged `fly_arena/data.py` in `tools/connectome/upstream_data.py`; MIT notice retained in `LICENSE-Fly-Arena.txt` |
| MaleCNS | v1.0 primary flat-connectome release | Annotated non-glial graph, IDs and soma landmarks; CC BY 4.0. URLs and hashes are in `tools/connectome/registered-manifest.json`. Raw data excluded from Git/image |
| FlyBody / Menagerie | `f3b6013629c7b94f8ee93fd977b161fa8350f9bc` | Scene context and derived schematic body routes; Apache-2.0. Frontend assets retain provenance and license; no unlicensed SIM-003 application code copied |
| NEURON | 9.0.1 | Compartment currents; BSD 3-clause, upstream notices retained in the distribution |
| LFPy / LFPykit | 2.3.6 / 0.6.2 | Extracellular forward operator; GPL v3 license files retained in installed distributions |
| NumPy / SciPy / scikit-learn | 2.2.6 / 1.15.3 / 1.6.1 | Arrays, numerical analysis and frozen training; upstream BSD notices and bundled-library notices apply |
| Numba / llvmlite | 0.67.0 / 0.49.0 | Sparse graph kernel compilation; upstream license and third-party notices retained |
| PyArrow | 19.0.1 runtime; 25.0.1 preparation | Scientific table serialization; Apache-2.0 |

The separate graph preparer uses NumPy 2.5.3 to reproduce the previously registered
byte format. Its compiler source SHA-256 and dependencies are documented under
`tools/connectome/`; no upstream SIM working tree is changed. Other SIMs were
design/implementation references, not copied application sources.
