"""Exact author binary and group metadata for the browser worker and UI."""

import hashlib
import shutil
import urllib.request

COMMIT = "9191824d17871b7851645782d53d23f213ddb938"
FILES = {
    "connectome.bin.gz": "5559a1ea2fdf7e65e476abd87ff542e4d0b00bf8",
    "neuron_meta.json": "425b8ec7a60e8065a551c670c64b655c2d0d82b7",
}


def identity(path, oid):
    size = path.stat().st_size
    sha, blob = hashlib.sha256(), hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            sha.update(chunk)
            blob.update(chunk)
    if blob.hexdigest() != oid:
        raise ValueError("Snedea pinned input Git blob differs: " + path.name)
    return {"bytes": size, "git_blob": oid, "sha256": sha.hexdigest()}


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent != WORK / "SIM-029":
        raise ValueError("Expected an owned SIM-029 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-029")
    if row["commit"] != COMMIT:
        raise ValueError("Unreviewed snedea commit")
    base = WORK / "SIM-029/assets"
    ledger = base / "requests.json"
    base.mkdir(parents=True, exist_ok=True)
    attempts = load(ledger) if ledger.exists() else {}
    save(ledger, attempts)
    inputs = []
    for name, oid in FILES.items():
        primary = base / name
        url = f"https://raw.githubusercontent.com/snedea/flybrain/{COMMIT}/data/{name}"
        records = attempts.setdefault(name, [])
        while not primary.exists() and len(records) < 2:
            item = {"attempt": len(records) + 1, "url": url, "status": "started"}
            records.append(item)
            save(ledger, attempts)
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
            save(ledger, attempts)
        if not primary.exists():
            raise ValueError("Registered browser input unavailable after two attempts")
        info = identity(primary, oid)
        destination = checked_work(run / "source/data" / name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(primary, destination)
        identity(destination, oid)
        inputs.append(
            {
                "file": "data/" + name,
                "url": url,
                "primary": primary.relative_to(ROOT).as_posix(),
                **info,
            }
        )
    save(run / "snedea-inputs.json", {"commit": COMMIT, "inputs": inputs})
