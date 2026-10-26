"""Acquire matched first ESN subnetworks from exact Git objects, not new data."""

import hashlib
import os
import subprocess
import urllib.request
from datetime import UTC, datetime

from inventory import REGISTRY, ROOT, load, save
from probes.optic_lobe_assets import prepare_font
from simctl import checked_work


def restore_frozen(run, row):
    reference = row["frozen_inputs"]
    manifest = checked_work(ROOT / reference["path"])
    if (
        manifest.parent.parent != run.parent
        or hashlib.sha256(manifest.read_bytes()).hexdigest() != reference["sha256"]
    ):
        raise ValueError("Frozen ESN manifest identity mismatch")
    receipt = load(manifest)
    expected = {
        f"inputs/{stage}/{group}.csv"
        for stage in ("larva", "adult")
        for group in ("connectome", "random", "cfg")
    }
    if (
        receipt["commit"] != row["commit"]
        or len(receipt["inputs"]) != 6
        or {x["file"] for x in receipt["inputs"]} != expected
    ):
        raise ValueError("Frozen ESN input set mismatch")
    for item in receipt["inputs"]:
        source = checked_work(manifest.parent / item["file"])
        content = source.read_bytes()
        blob = hashlib.sha1(
            b"blob " + str(len(content)).encode() + b"\0" + content
        ).hexdigest()
        if (
            hashlib.sha256(content).hexdigest() != item["sha256"]
            or blob != item["git_blob"]
        ):
            raise ValueError("Frozen ESN matrix changed")
        target = checked_work(run / item["file"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    receipt["reuse"] = {
        "manifest": reference["path"],
        "sha256": reference["sha256"],
        "network_attempts": 0,
        "date": datetime.now(UTC).isoformat(),
    }
    save(run / "conn-esn-inputs.json", receipt)
    prepare_font(run)


def hydrate(run):
    run = checked_work(run)
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-013")
    if row.get("frozen_inputs"):
        restore_frozen(run, row)
        return
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1")
    receipt = {
        "commit": row["commit"],
        "selection": "subnetwork_1/matrix1.csv for each stage and topology; no performance-based selection",
        "inputs": [],
    }
    for stage in ("larva", "adult"):
        for topology in ("connectome", "random", "cfg"):
            name = f"esn_weight_matrices/{topology}/{stage}/subnetwork_1/matrix1.csv"
            raw = subprocess.check_output(
                ["git", "ls-tree", row["commit"], "--", name],
                cwd=ROOT / row["path"],
                env=env,
                text=True,
                timeout=15,
            ).strip()
            metadata, found = raw.split("\t", 1)
            mode, kind, oid = metadata.split()
            if found != name or mode != "100644" or kind != "blob":
                raise ValueError("Unexpected pinned ESN tree entry")
            url = f"https://raw.githubusercontent.com/{row['repository']}/{row['commit']}/{name}"
            target = checked_work(run / "inputs" / stage / (topology + ".csv"))
            target.parent.mkdir(parents=True, exist_ok=True)
            failures = []
            for attempt in (1, 2):
                try:
                    with urllib.request.urlopen(url, timeout=90) as response:
                        content = response.read(512 * 1024**2 + 1)
                    if len(content) > 512 * 1024**2:
                        raise ValueError("Unexpected single-matrix download size")
                    actual = hashlib.sha1(
                        b"blob " + str(len(content)).encode() + b"\0" + content
                    ).hexdigest()
                    if actual != oid:
                        raise ValueError("ESN weights differ from pinned Git blob")
                    target.write_bytes(content)
                    break
                except (OSError, ValueError) as exc:
                    failures.append(str(exc))
            else:
                raise ValueError(
                    "Pinned ESN matrix unavailable twice: " + repr(failures)
                )
            receipt["inputs"].append(
                {
                    "file": target.relative_to(run).as_posix(),
                    "git_path": name,
                    "git_blob": oid,
                    "url": url,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "attempt": attempt,
                    "failed_attempts": failures,
                }
            )
            print("ESN input", stage, topology, len(content), flush=True)
    save(run / "conn-esn-inputs.json", receipt)
    prepare_font(run)
