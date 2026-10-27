# Registered MaleCNS graph preparation

`upstream_data.py` is an unchanged copy of `fly_arena/data.py` from Fly Arena,
commit `12f48c702ed170b5bdc4643afa7ce65e952b353d`, MIT. Its SHA-256 is
`1c5189f6eaaff3f4a0525f6ced9124b02bb752057291681acc67800509a5a243`.
The [upstream license](../../service/infrastructure/connectome/LICENSE-Fly-Arena.txt)
is retained. The three primary MaleCNS v1.0 files are CC BY 4.0 and are linked
with sizes and hashes in `registered-manifest.json`; they are not included in Git.

The compiler retains every edge between annotated non-glial entries. Its retinal
port map is retained for byte-for-byte provenance but is not used as the tactile
input or as the extracellular recording operator. No Fly Arena app code runs in
the backend. Original SIM sources remain unchanged.

NumPy 2.5.3 / PyArrow 25.0.1 / Numba 0.67.0 reproduce the original serialization.
This preparation container is separate from the numerical runtime (NumPy 2.2.6 /
PyArrow 19.0.1). Do not change the runtime to prepare a dataset.

From `generator/`:

```sh
docker build -f docker/Dockerfile.connectome -t aiscs-connectome-preparer:1 .
docker run --rm -v aiscs-male-cns:/data aiscs-connectome-preparer:1 --output /data
```

The command downloads at most twice per primary file, verifies SHA-256, builds
under `.preparation`, verifies every array and the annotations, then publishes
`graph/`. Interrupted preparation does not alter an existing graph. Repeating
the command verifies an existing graph without rebuilding it; invalid existing
data cause an error. The raw directory is retained for offline resume.

For an existing primary-file directory, mount it read-only as `/raw` and add
`--raw /raw --offline`. The offline preparation was reproduced with all seven
registered file hashes and the manifest matching exactly. Mount the resulting
volume read-only at `/datasets` in the runtime and set
`GENERATOR_CONNECTOME_DIR=/datasets/graph`. Alternatively use the platform's
own generator volume and `/work/datasets/malecns-v1` output directory. Never
copy the raw files into an image or Git.
