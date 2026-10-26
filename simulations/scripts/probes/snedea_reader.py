"""Read binary recordings using only the standard library, without the simulator."""

import argparse
import array
import collections
import gzip
import hashlib
import json
import math
import struct
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run = Path(args.run).resolve()
    root = Path(__file__).resolve().parents[3]
    base = root / "research/.work/simulator-evaluation/SIM-029"
    assert run.parent == base
    out = run / "exports"
    summary = json.loads((out / "worker.json").read_text())
    meta = json.loads((run / "source/data/neuron_meta.json").read_text())
    n, e = summary["neurons"], summary["edges"]
    assert (n, e) == (139255, 2698236)
    permutation = array.array("I")
    with gzip.open(out / "worker-to-author-binary-index.u32.gz", "rb") as stream:
        permutation.frombytes(stream.read())
    if sys.byteorder != "little":
        permutation.byteswap()
    assert len(permutation) == len(set(permutation)) == n
    assert min(permutation) == 0 and max(permutation) == n - 1
    with gzip.open(run / "source/data/connectome.bin.gz", "rb") as stream:
        assert struct.unpack("<II", stream.read(8)) == (n, e)
        stream.seek(8 + e * 12)
        raw = stream.read(n * 3)
        assert not stream.read(1)
    original_groups = [group for _, group in struct.iter_unpack("<BH", raw)]
    groups = [original_groups[index] for index in permutation]
    assert groups == sorted(original_groups)
    assert [groups.count(i) for i in range(63)] == meta["group_sizes"]
    checked = []
    for item in summary["runs"]:
        states = (out / item["state_export"]).resolve()
        events = (out / item["event_export"]).resolve()
        assert states.parent == events.parent == out.resolve()
        assert (
            hashlib.sha256(states.read_bytes()).hexdigest() == item["state_file_sha256"]
        )
        assert (
            hashlib.sha256(events.read_bytes()).hexdigest() == item["event_file_sha256"]
        )
        data = json.loads(events.read_text())
        by_tick = collections.defaultdict(list)
        for tick, index, group in data["rows"]:
            assert 0 <= tick < 120 and 0 <= index < n and groups[index] == group
            by_tick[tick].append(index)
        selected = set(item["stimulated_indices"])
        assert (
            sum(index not in selected for _, index, _ in data["rows"])
            == item["events_outside_stimulated"]
        )
        assert len(data["rows"]) == item["total_events"]
        digest = hashlib.sha256()
        low, high = math.inf, -math.inf
        with gzip.open(states, "rb") as stream:
            for tick in range(120):
                raw = stream.read(n * 4)
                assert len(raw) == n * 4
                digest.update(raw)
                values = array.array("f")
                values.frombytes(raw)
                if sys.byteorder != "little":
                    values.byteswap()
                assert all(map(math.isfinite, values))
                low, high = min(low, min(values)), max(high, max(values))
                assert len(by_tick[tick]) == item["series"][tick]["events"]
                assert len(set(by_tick[tick])) == len(by_tick[tick])
                assert all(values[index] == 0 for index in by_tick[tick])
            assert not stream.read(1)
        assert digest.hexdigest() == item["state_array_sha256"]
        checked.append(
            {
                "name": item["name"],
                "finite_values_checked": 120 * n,
                "events": len(data["rows"]),
                "min_model_potential": low,
                "max_model_potential": high,
            }
        )
    assert (
        summary["runs"][0]["state_array_sha256"]
        == summary["runs"][3]["state_array_sha256"]
    )
    result = {
        "status": "passed",
        "project_model_imported": False,
        "third_party_packages": [],
        "repeat_seed_equal": True,
        "permutation_verified": True,
        "original_root_ids": "absent from the two registered runtime inputs",
        "checked": checked,
    }
    (out / "independent-reader.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "values_checked": sum(x["finite_values_checked"] for x in checked),
                "runs": len(checked),
            }
        )
    )


if __name__ == "__main__":
    main()
