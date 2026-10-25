"""Reproduce author graph preparation on registered MaleCNS files, not neural dynamics."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

SOURCE = Path("/work/source")
DATA = Path("/work/assets/malecns")
EXPORT = Path("/work/exports/malecns-depth")
EXPECTED = "cd6bbde8abf155fa746aaa64afc34f5c5b2454ac7867426a2a4972fc2566b0e8"
INPUTS = {
    "body-annotations.feather": "50a7718770c57220f160ba4f431ab89e",
    "body-nt.feather": "3d842b12fe5c49eefade528d7dd24a1f",
    "connectome-weights.feather": "f30e9dcca25cfd021bf1e7b3d975599e",
}


def file_digest(path, algorithm):
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def graph_content(path):
    digest = hashlib.sha256()
    shapes = {}
    with np.load(path) as data:
        ids = data["body_ids"]
        assert len(ids) == 166700 and np.all(np.diff(ids) > 0)
        edges = len(data["pre"])
        for name in ("pre", "post", "w", "body_ids"):
            array = np.ascontiguousarray(data[name])
            assert np.isfinite(array).all()
            if name in {"pre", "post"}:
                assert (
                    len(array) == edges and array.min() >= 0 and array.max() < len(ids)
                )
            if name == "w":
                assert len(array) == edges and array.min() > 0
            digest.update(name.encode())
            digest.update(str(array.dtype).encode())
            digest.update(array.tobytes())
            shapes[name] = {"shape": list(array.shape), "dtype": str(array.dtype)}
        synapses = int(data["w"].sum())
    return {
        "content_sha256": digest.hexdigest(),
        "neurons": len(ids),
        "connectivity_rows": edges,
        "synapse_weight_sum": synapses,
        "arrays": shapes,
    }


def main():
    EXPORT.mkdir(parents=True, exist_ok=True)
    inputs = {}
    for name, expected in INPUTS.items():
        path = DATA / name
        assert file_digest(path, "md5") == expected, name
        inputs[name] = {
            "bytes": path.stat().st_size,
            "md5": expected,
            "sha256": file_digest(path, "sha256"),
        }
    trials = []
    env = dict(os.environ, MALECNS_DATA=str(DATA), PYTHONUNBUFFERED="1")
    for attempt in (1, 2):
        log = EXPORT / f"build-graph-attempt{attempt}.log"
        with log.open("w", encoding="utf-8") as output:
            subprocess.run(
                [sys.executable, str(SOURCE / "code/build_graph.py")],
                env=env,
                cwd=SOURCE,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
            )
        result = graph_content(DATA / "neuron_edges.npz")
        assert result["content_sha256"] == EXPECTED, result
        trials.append(result)
        print(json.dumps({"attempt": attempt, **result}), flush=True)
    assert trials[0] == trials[1]
    result = {
        "status": "passed",
        "scope": "author preparation of the real MaleCNS v1.0 graph",
        "inputs": inputs,
        "trials": trials,
        "repeat_content_equal": True,
        "author_frozen_content_sha256_matches": True,
        "seed_applicability": "Graph preparation is deterministic, with no random seed",
        "limitations": [
            "No spike simulation",
            "No body or environment",
            "No human ECAP",
            "Confirmatory h1-h5 on the real graph not reproduced by this scenario",
            "Full confirmatory gate also requires the separate syn-partners file",
        ],
    }
    (EXPORT / "real-graph-result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
