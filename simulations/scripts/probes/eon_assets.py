"""Restore the two pinned FlyWire v783 Git blobs into an isolated work copy."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

FILES = ("data/2025_Completeness_783.csv", "data/2025_Connectivity_783.parquet")


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save

    run = Path(run).resolve()
    if not run.is_relative_to(WORK.resolve()) or run.parent.name != "SIM-006":
        raise ValueError("Eon data must be restored inside the SIM-006 work directory")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-006")
    base = ROOT / row["path"]
    tree = subprocess.check_output(
        ["git", "ls-tree", "-l", row["commit"], "--", *FILES],
        cwd=base,
        timeout=30,
    ).decode("utf-8")
    entries = []
    for line in tree.splitlines():
        metadata, name = line.split("\t", 1)
        mode, kind, oid, size = metadata.split()
        if name not in FILES or mode != "100644" or kind != "blob":
            raise ValueError("Unexpected pinned Eon data entry")
        target = run / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".partial")
            try:
                with temporary.open("wb") as output:
                    subprocess.run(
                        ["git", "cat-file", "blob", oid],
                        cwd=base,
                        stdout=output,
                        stderr=subprocess.PIPE,
                        timeout=180,
                        check=True,
                    )
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        sha = hashlib.sha256()
        git_sha = hashlib.sha1(b"blob " + size.encode() + b"\0")
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
                git_sha.update(chunk)
        if target.stat().st_size != int(size) or git_sha.hexdigest() != oid:
            raise ValueError("Pinned Eon data mismatch: " + name)
        entries.append(
            {
                "path": name,
                "bytes": int(size),
                "git_blob": oid,
                "sha256": sha.hexdigest(),
                "version": "FlyWire v783",
            }
        )
    if {x["path"] for x in entries} != set(FILES):
        raise ValueError("The pinned Eon tree does not contain both v783 inputs")
    save(run / "pinned-assets.json", {"commit": row["commit"], "restored": entries})
    print(
        "Eon: verified two pinned v783 inputs; upstream checkout unchanged", flush=True
    )
