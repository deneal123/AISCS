"""Restore exact pinned Git blobs into an isolated Infinite Sugar work copy."""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import REGISTRY, ROOT, load, save
from simctl import checked_work, command


def hydrate(run):
    run = checked_work(run)
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-003")
    if run.parent.name != row["id"]:
        raise ValueError("Wrong candidate work directory")
    base = ROOT / row["path"]
    tree = command(["git", "ls-tree", "-r", "--long", row["commit"]], cwd=base)
    if tree.returncode:
        raise ValueError("Cannot inspect pinned Git tree")
    receipt = run / "pinned-assets.json"
    restored = load(receipt)["restored"] if receipt.exists() else []
    for line in tree.stdout.splitlines():
        metadata, name = line.split("\t", 1)
        mode, kind, oid, size = metadata.split()
        if kind != "blob" or mode not in {"100644", "100755"} or int(size) > 32 * 1024**2:
            raise ValueError("Unqualified tree entry")
        target = checked_work(run / "source" / name)
        if target.exists():
            continue
        content = subprocess.run(["git", "cat-file", "blob", oid], cwd=base, capture_output=True, timeout=90, check=True).stdout
        actual = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if len(content) != int(size) or actual != oid:
            raise ValueError("Git blob mismatch: " + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        restored.append({"path": name, "git_blob": oid, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    save(run / "pinned-assets.json", {"commit": row["commit"], "restored": restored})
    print("Restored", len(restored), "pinned files; upstream untouched")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run")
    args = parser.parse_args()
    hydrate(ROOT / args.run)


if __name__ == "__main__":
    main()
