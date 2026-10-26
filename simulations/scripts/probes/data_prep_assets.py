"""Restore the registered larval preparation inputs, retaining their exact Git identity."""

import hashlib
import shutil
import urllib.request

COMMIT = "a4df3b0d5345d2a34dac813f897d8427f6a6eb45"
FILES = {
    "data/ad_connectivity_matrix.csv": "9ccf06668dbb0efbbcb165245e5689c6625e9aa0",
    "data/larva/larva_ad_inprop.npz": "65aaad98d3edec8ba6a0d848ed099e0194f1dc12",
    "data/larva/larva_ad_syncount.npz": "07343a0ed18662516ecad581091052b2e4f3a644",
    "data/larva/larva_all_inprop.npz": "4467c231c508707b0bf6cd9c0bf8f322b76d455d",
    "data/larva/larva_all_syncount.npz": "8d3a4cdbf6839e268bfcfcb89daf02e2a265878d",
    "data/larva/larva_all_neuron_meta.csv": "cd6e063199882d8ed064bee1d1fcd5d0d0931955",
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
        raise ValueError("Data-preparation input differs from pinned Git blob")
    return {"bytes": size, "git_blob": oid, "sha256": sha.hexdigest()}


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    assert run.parent == WORK / "SIM-033"
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-033")
    assert row["commit"] == COMMIT
    base = WORK / "SIM-033/assets"
    base.mkdir(parents=True, exist_ok=True)
    ledger = base / "requests.json"
    records = load(ledger) if ledger.exists() else {}
    inputs = []
    for name, oid in FILES.items():
        primary = base / name
        primary.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/YijieYin/connectome_data_prep/{COMMIT}/{name}"
        attempts = records.setdefault(name, [])
        while not primary.exists() and len(attempts) < 2:
            item = {"url": url, "attempt": len(attempts) + 1, "status": "started"}
            attempts.append(item)
            save(ledger, records)
            partial = primary.with_suffix(primary.suffix + ".partial")
            try:
                with (
                    urllib.request.urlopen(url, timeout=180) as response,
                    partial.open("wb") as stream,
                ):
                    shutil.copyfileobj(response, stream, 1024**2)
                item.update(identity(partial, oid), status="verified")
                partial.replace(primary)
            except (OSError, ValueError) as exc:
                item.update(status="failed", error=str(exc))
                partial.unlink(missing_ok=True)
            save(ledger, records)
        if not primary.exists():
            raise ValueError("Registered larval data unavailable after two attempts")
        info = identity(primary, oid)
        target = checked_work(run / "source" / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != primary.read_bytes():
            assert name.endswith(".csv") and target.read_bytes().replace(
                b"\r\n", b"\n"
            ) == primary.read_bytes().replace(b"\r\n", b"\n")
        shutil.copyfile(primary, target)
        inputs.append(
            {
                "file": name,
                "primary": primary.relative_to(ROOT).as_posix(),
                "url": url,
                **info,
            }
        )
    save(run / "data-prep-inputs.json", {"commit": COMMIT, "inputs": inputs})
