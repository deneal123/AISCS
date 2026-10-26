"""Recover original Shiu v630 files by their registered Git blob identities."""

import hashlib
import os
import shutil
import subprocess
import urllib.request

COMMIT = "91bdd1e7dcf193f3e7ca5a8933497fcef63b7960"
FILES = {
    "2023_03_23_completeness_630_final.csv": "be745f0ce054308df21accc5c4b3883aa38498f9",
    "2023_03_23_connectivity_630_final.parquet": "8b4d9531bc0acbda7c2074ae577e6ac9e2fca166",
}


def identity(path, oid):
    size = path.stat().st_size
    blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            blob.update(chunk)
            sha.update(chunk)
    if blob.hexdigest() != oid:
        raise ValueError("Shiu pinned input Git blob mismatch: " + path.name)
    return {"bytes": size, "git_blob": oid, "sha256": sha.hexdigest()}


def copy_verified(primary, destination, oid):
    from simctl import checked_work

    primary, destination = checked_work(primary), checked_work(destination)
    info = identity(primary, oid)
    if destination.exists():
        identity(destination, oid)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(primary, destination)
        identity(destination, oid)
    return info


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent.name != "SIM-024":
        raise ValueError("Shiu inputs require an owned SIM-024 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-024")
    if row["commit"] != COMMIT:
        raise ValueError("Unreviewed Shiu commit")
    tree = subprocess.check_output(
        ["git", "ls-tree", COMMIT, *FILES],
        cwd=ROOT / row["path"],
        text=True,
        timeout=30,
        env=dict(os.environ, GIT_NO_LAZY_FETCH="1"),
    )
    actual = {}
    for line in tree.splitlines():
        metadata, name = line.split("\t")
        mode, kind, oid = metadata.split()
        if mode != "100644" or kind != "blob":
            raise ValueError("Shiu input must be a regular registered Git blob")
        actual[name] = oid
    if actual != FILES:
        raise ValueError("Shiu pinned input tree differs")
    assets = WORK / "SIM-024/assets"
    assets.mkdir(parents=True, exist_ok=True)
    cache = WORK / "SIM-022/20261026T114343Z-c380a1/source/data"
    ledger = assets / "requests.json"
    requests = load(ledger) if ledger.exists() else {}
    inputs = []
    for name, oid in FILES.items():
        primary = cache / name
        url = f"https://raw.githubusercontent.com/{row['repository']}/{COMMIT}/{name}"
        if not primary.is_file():
            primary = assets / name
            attempts = requests.setdefault(name, [])
            while not primary.exists() and len(attempts) < 2:
                item = {"attempt": len(attempts) + 1, "url": url, "status": "started"}
                attempts.append(item)
                save(ledger, requests)
                partial = primary.with_suffix(primary.suffix + ".partial")
                try:
                    with (
                        urllib.request.urlopen(url, timeout=60) as response,
                        partial.open("wb") as stream,
                    ):
                        shutil.copyfileobj(response, stream, 1024**2)
                    identity(partial, oid)
                    partial.replace(primary)
                    item["status"] = "verified"
                except (OSError, ValueError) as exc:
                    item.update(status="failed", error=str(exc))
                    partial.unlink(missing_ok=True)
                save(ledger, requests)
            if not primary.exists():
                raise ValueError("Original Shiu input unavailable after two attempts")
        info = copy_verified(primary, run / "source" / name, oid)
        inputs.append(
            {
                "file": name,
                **info,
                "primary": primary.relative_to(ROOT).as_posix(),
                "url": url,
            }
        )
    save(run / "shiu-inputs.json", {"commit": COMMIT, "inputs": inputs})
    (run / "build-constraints.txt").write_text(
        "setuptools==67.8.0\nnumpy==1.24.4\nCython==0.29.33\n",
        encoding="utf-8",
        newline="\n",
    )
