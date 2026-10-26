"""Recover the exact tutorial MANC inputs without expanding the sparse sidecar."""

import hashlib
import os
import shutil
import subprocess
import urllib.parse
import urllib.request

COMMIT = "10e7661bf414ba7b4c2edf795cd36d0f878c17c0"
FILES = {
    "data/manc t1 connectome data/W_20250813_DNtoMN_unsorted.csv": (
        "3c21cac955635a518013a6fce56aac3d8a223acb",
        85037890,
    ),
    "data/manc t1 connectome data/wTable_20250813_DNtoMN_unsorted_withModules.csv": (
        "071da7f6eeb4707c3ef899c30c79d09322782f7b",
        671375,
    ),
}


def identity(path, oid, size):
    if path.stat().st_size != size:
        raise ValueError("Pugliese input size differs: " + path.name)
    blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            blob.update(chunk)
            sha.update(chunk)
    if blob.hexdigest() != oid:
        raise ValueError("Pugliese input Git identity differs: " + path.name)
    return {"bytes": size, "git_blob": oid, "sha256": sha.hexdigest()}


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent != WORK / "SIM-027":
        raise ValueError("Expected an owned SIM-027 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-027")
    if row["commit"] != COMMIT:
        raise ValueError("Unreviewed Pugliese commit")
    sidecar = ROOT / row["path"]
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1")
    tree = subprocess.check_output(
        ["git", "ls-tree", COMMIT, *FILES],
        cwd=sidecar,
        env=env,
        text=True,
        timeout=30,
    )
    actual = {line.split("\t")[1]: line.split()[2] for line in tree.splitlines()}
    if actual != {name: item[0] for name, item in FILES.items()}:
        raise ValueError("Pinned tutorial data tree differs")
    assets = checked_work(WORK / "SIM-027/assets")
    assets.mkdir(parents=True, exist_ok=True)
    ledger = assets / "requests.json"
    requests = load(ledger) if ledger.exists() else {}
    save(ledger, requests)
    inputs = []
    for name, (oid, size) in FILES.items():
        primary = assets / name.rsplit("/", 1)[1]
        url = (
            f"https://raw.githubusercontent.com/{row['repository']}/{COMMIT}/"
            + urllib.parse.quote(name)
        )
        if not primary.exists():
            local = subprocess.run(
                ["git", "cat-file", "-e", oid],
                cwd=sidecar,
                env=env,
                capture_output=True,
                check=False,
                timeout=30,
            )
            partial = primary.with_suffix(primary.suffix + ".partial")
            if local.returncode == 0:
                with partial.open("wb") as stream:
                    subprocess.run(
                        ["git", "cat-file", "blob", oid],
                        cwd=sidecar,
                        env=env,
                        stdout=stream,
                        check=True,
                        timeout=120,
                    )
                identity(partial, oid, size)
                partial.replace(primary)
            else:
                attempts = requests.setdefault(name, [])
                while not primary.exists() and len(attempts) < 2:
                    item = {
                        "url": url,
                        "attempt": len(attempts) + 1,
                        "status": "started",
                    }
                    attempts.append(item)
                    save(ledger, requests)
                    try:
                        with (
                            urllib.request.urlopen(url, timeout=90) as response,
                            partial.open("wb") as stream,
                        ):
                            shutil.copyfileobj(response, stream, 1024**2)
                        identity(partial, oid, size)
                        partial.replace(primary)
                        item["status"] = "verified"
                    except (OSError, ValueError) as exc:
                        item.update(status="failed", error=str(exc))
                        partial.unlink(missing_ok=True)
                    save(ledger, requests)
                if not primary.exists():
                    raise ValueError(
                        "Registered MANC input unavailable after two attempts"
                    )
        info = identity(primary, oid, size)
        destination = checked_work(run / "source" / name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(primary, destination)
        identity(destination, oid, size)
        inputs.append(
            {
                "file": name,
                "url": url,
                "primary": primary.relative_to(ROOT).as_posix(),
                **info,
            }
        )
    save(run / "pugliese-inputs.json", {"commit": COMMIT, "inputs": inputs})
