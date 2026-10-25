"""Repeat the author's synthetic graph fixture; this is not measured biology."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "/work/source/code/confirmatory/tests")
import make_synthetic

output = Path("/work/exports/malecns-depth")
output.mkdir(parents=True, exist_ok=True)
trials = []
reference = None
for attempt, seed in enumerate((1, 2, 3, 1)):
    directory = output / f"synthetic-seed{seed}-attempt{attempt}"
    info = make_synthetic.make(str(directory), seed=seed)
    with np.load(directory / "neuron_edges.npz") as source:
        arrays = {key: source[key] for key in ("pre", "post", "w", "body_ids")}
    assert len(arrays["body_ids"]) == info["N"]
    assert np.all(np.diff(arrays["body_ids"]) > 0)
    digest = hashlib.sha256()
    for key, array in arrays.items():
        assert np.isfinite(array).all()
        digest.update(key.encode())
        digest.update(str(array.dtype).encode())
        digest.update(array.tobytes())
    if attempt == 0:
        reference = arrays
    if attempt == 3:
        for key, array in arrays.items():
            np.testing.assert_array_equal(reference[key], array)
    trials.append({"seed": seed, "content_sha256": digest.hexdigest(), **info})
assert len({item["content_sha256"] for item in trials[:3]}) == 3
result = {
    "status": "passed",
    "scope": "author synthetic graph generator, not real MaleCNS",
    "trials": trials,
    "repeat_seed_equal": True,
    "different_seeds_produce_different_graphs": True,
}
(output / "synthetic-seeds-result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result), flush=True)
