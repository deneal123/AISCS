"""Restore two small authored SWC exports, never the entire sparse data tree."""

import hashlib
import os
import subprocess
import urllib.request
from datetime import UTC, datetime

from inventory import REGISTRY, ROOT, load, save
from simctl import checked_work

NAMES = [
    "example_notebooks/output/648518346486614449_high-res-skeleton.swc",
    "example_notebooks/output/648518346486614449_pcg-skel.swc",
]


def hydrate(run):
    run = checked_work(run)
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-012")
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1")
    result = {
        "commit": row["commit"],
        "inputs": [],
        "materialization": "not established for these authored SWC files",
    }
    for name in NAMES:
        line = subprocess.check_output(
            ["git", "ls-tree", row["commit"], "--", name],
            cwd=ROOT / row["path"],
            env=env,
            text=True,
            timeout=15,
        ).strip()
        metadata, found = line.split("\t")
        mode, kind, oid = metadata.split()
        if found != name or mode != "100644" or kind != "blob":
            raise ValueError("Unexpected SWC Git tree entry")
        url = f"https://raw.githubusercontent.com/htem/FANC_auto_recon/{row['commit']}/{name}"
        failures = []
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    data = response.read(8 * 1024**2 + 1)
                if len(data) > 8 * 1024**2:
                    raise ValueError("SWC exceeds qualified small-export bound")
                actual = hashlib.sha1(
                    b"blob " + str(len(data)).encode() + b"\0" + data
                ).hexdigest()
                if actual != oid or b"<html" in data[:100].lower():
                    raise ValueError("SWC does not match the pinned Git blob")
                break
            except (OSError, ValueError) as exc:
                failures.append(str(exc))
        else:
            raise ValueError("Pinned SWC unavailable twice: " + repr(failures))
        target = checked_work(run / "inputs" / name.rsplit("/", 1)[1])
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
        result["inputs"].append(
            {
                "file": target.relative_to(run).as_posix(),
                "url": url,
                "git_blob": oid,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "attempt": attempt,
                "failed_attempts": failures,
            }
        )
    save(run / "fanc-inputs.json", result)
    print("Pinned FANC SWC exports verified", flush=True)
