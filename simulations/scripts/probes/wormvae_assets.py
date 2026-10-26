"""Restore only the exact author worm recordings and connectome tables."""

import hashlib
import shutil
import urllib.request

COMMIT = "15b58bff08bdf4eb04709434d766fca6835d7d79"
FILES = {
    "data/worm_activity/all_traces_Heads_new.mat": "3b76a42428e14efd61b7bb28a823c59de4367d76",
    "data/worm_connectivity/chem.csv": "a603dfe5a2cf40835ecdfccfd16cf11f91958046",
    "data/worm_connectivity/elec_asymmetric.csv": "f1eb18a8484140ba37b41a16f5b608afd20b77da",
    "data/worm_connectivity/elec_symmetric.csv": "ea2026434c6378c223e2bb9edeef0f4516f57e46",
    "data/worm_connectivity/herm_specific_cells.csv": "b7a525b129eb52898ec673aa505895257d9dd646",
    "data/worm_connectivity/sex_shared_cells.csv": "feb2e1aef5442806968a788f28ed11642c0aac08",
    "data/worm_connectivity/white_neuron_connect.csv": "a1309a09d2f529d264be30c5a3de601b2edb1593",
    "data/worm_connectivity/white_neuron_types.csv": "5265dfb2f688c6fe113dab44781d44beae7ca4a8",
}


def identity(path, oid):
    data = path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if blob != oid:
        raise ValueError("Wormvae input differs from pinned Git blob")
    return {
        "bytes": len(data),
        "git_blob": oid,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    assert run.parent == WORK / "SIM-032"
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-032")
    assert row["commit"] == COMMIT
    base = WORK / "SIM-032/assets"
    base.mkdir(parents=True, exist_ok=True)
    ledger = base / "requests.json"
    records = load(ledger) if ledger.exists() else {}
    inputs = []
    for name, oid in FILES.items():
        primary = base / name
        primary.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/TuragaLab/wormvae/{COMMIT}/{name}"
        attempts = records.setdefault(name, [])
        while not primary.exists() and len(attempts) < 2:
            item = {"url": url, "attempt": len(attempts) + 1, "status": "started"}
            attempts.append(item)
            save(ledger, records)
            partial = primary.with_suffix(primary.suffix + ".partial")
            try:
                with (
                    urllib.request.urlopen(url, timeout=90) as response,
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
            raise ValueError("Registered worm data unavailable after two attempts")
        info = identity(primary, oid)
        target = checked_work(run / "source" / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Checkout conversion is allowed only when it preserves the exact text.
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
    save(run / "wormvae-inputs.json", {"commit": COMMIT, "inputs": inputs})
