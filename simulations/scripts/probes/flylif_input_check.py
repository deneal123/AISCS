"""Stream-check the real alternate CSV without allocating one object per edge."""

import csv
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

run = Path("/work")
manifest = json.loads((run / "flylif-inputs.json").read_text())
connections = next(
    x
    for x in manifest["inputs"]
    if x["derived_file"].endswith("connections_no_threshold.csv")
)
path = run / connections["derived_file"]
with path.open("rb") as stream:
    assert (
        hashlib.file_digest(stream, "sha256").hexdigest()
        == connections["derived_sha256"]
    )
nodes = set()
counts = Counter()
rows = total = 0
started = time.monotonic()
with path.open(newline="") as stream:
    reader = csv.DictReader(stream)
    assert reader.fieldnames == [
        "pre_root_id",
        "post_root_id",
        "neuropil",
        "syn_count",
        "nt_type",
    ]
    for item in reader:
        count = int(item["syn_count"])
        assert (
            count >= 0
            and item["pre_root_id"].isdigit()
            and item["post_root_id"].isdigit()
        )
        nodes.add(item["pre_root_id"])
        nodes.add(item["post_root_id"])
        total += count
        rows += 1
        counts[item["nt_type"]] += 1
        if rows % 5000000 == 0:
            print("Input rows checked", rows, flush=True)
out = {
    "status": "passed",
    "scope": "Input audit only, no neural simulation or exact paper reproduction",
    "raw_rows": rows,
    "unique_endpoint_ids": len(nodes),
    "summed_syn_count": total,
    "nt_rows": dict(counts),
    "seconds": time.monotonic() - started,
    "derived_sha256": connections["derived_sha256"],
    "primary_manifest": manifest["primary_manifest"],
}
(run / "input-stream-check.json").write_text(
    json.dumps(out, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(out, indent=2), flush=True)
