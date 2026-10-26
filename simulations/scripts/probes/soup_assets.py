"""Restore small pinned browser sources omitted by the sparse sidecar checkout."""

import hashlib
import os
import subprocess
import urllib.request

from inventory import REGISTRY, ROOT, load, save
from simctl import checked_work


def hydrate(run):
    run = checked_work(run)
    if run.parent.name != "SIM-016":
        raise ValueError("Browser sources require an owned SIM-016 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-016")
    repository = ROOT / row["path"]
    entries = []
    for name in ("web/test/e2e.html", "web/test/fullscale.html", "web/wasm/Cargo.lock"):
        metadata = subprocess.check_output(
            ["git", "ls-tree", row["commit"], "--", name],
            cwd=repository,
            env=dict(os.environ, GIT_NO_LAZY_FETCH="1"),
            text=True,
            timeout=30,
        ).strip()
        fields, found = metadata.split("\t")
        mode, kind, oid = fields.split()
        if found != name or mode != "100644" or kind != "blob":
            raise ValueError("Unexpected browser Git entry")
        local = subprocess.run(
            ["git", "cat-file", "blob", oid],
            cwd=repository,
            env=dict(os.environ, GIT_NO_LAZY_FETCH="1"),
            capture_output=True,
            timeout=30,
            check=False,
        )
        route = "local Git object"
        if local.returncode == 0:
            content = local.stdout
        else:
            route = f"https://raw.githubusercontent.com/{row['repository']}/{row['commit']}/{name}"
            for attempt in (1, 2):
                try:
                    with urllib.request.urlopen(route, timeout=30) as response:
                        content = response.read(1024**2 + 1)
                    break
                except OSError:
                    if attempt == 2:
                        raise
        actual = hashlib.sha1(
            b"blob " + str(len(content)).encode() + b"\0" + content
        ).hexdigest()
        if len(content) > 1024**2 or actual != oid:
            raise ValueError("Pinned browser source identity mismatch")
        target = checked_work(run / "source" / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        entries.append(
            {
                "file": name,
                "git_blob": oid,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "route": route,
            }
        )
    save(
        run / "supplemental-source-files.json",
        {"commit": row["commit"], "files": entries},
    )
