"""Bind FlyConnectome tutorials to the checked public metadata snapshot."""

import hashlib
import shutil
import time
import urllib.request

from inventory import REGISTRY, ROOT, WORK, load, save
from simctl import checked_work

COMMIT = "9b1790b5553082e1f57921790564c7aae7c9c99a"
ROUTES = {
    "segmentation-v630": "https://storage.googleapis.com/flywire_v141_m630/info",
    "segmentation-v783": "https://storage.googleapis.com/flywire_v141_m783/info",
    "neuropil-v5": "https://storage.googleapis.com/flywire_neuropil_meshes/neuropils/neuropil_mesh_v141_v5/info",
    "whole-neuropil-v3": "https://storage.googleapis.com/flywire_neuropil_meshes/whole_neuropil/brain_mesh_v3/info",
    "em-fafb-v14": "https://bossdb-open-data.s3.amazonaws.com/flywire/fafbv14/info",
}


def acquire_metadata(base, routes):
    if set(routes) != set(ROUTES):
        raise ValueError("Expected the five registered FlyConnectome routes")
    ledger = base / "metadata-requests.json"
    attempts = load(ledger) if ledger.exists() else {}
    if not ledger.exists():
        save(ledger, attempts)
    for name, item in routes.items():
        if item["url"] != ROUTES[name] or item["file"] != name + "-info.json":
            raise ValueError("Unreviewed FlyConnectome metadata route")
        path = checked_work(base / item["file"])
        if (
            path.exists()
            and hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError(
                "Public metadata snapshot changed; preserve the existing file"
            )
        records = attempts.setdefault(name, [])
        while not path.exists() and len(records) < 2:
            record = {
                "attempt": len(records) + 1,
                "url": item["url"],
                "status": "started",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            records.append(record)
            save(ledger, attempts)
            try:
                with urllib.request.urlopen(item["url"], timeout=30) as response:
                    payload = response.read(item["bytes"] + 1)
                if (
                    len(payload) != item["bytes"]
                    or hashlib.sha256(payload).hexdigest() != item["sha256"]
                ):
                    raise ValueError("Registered metadata size or hash mismatch")
                path.write_bytes(payload)
                record["status"] = "verified"
            except (OSError, ValueError) as exc:
                record.update(status="failed", error=str(exc))
            save(ledger, attempts)
        if not path.exists():
            raise ValueError(
                "Registered public metadata unavailable after two attempts"
            )
    return {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "routes": routes,
        "requests": ledger.relative_to(ROOT).as_posix(),
    }


def hydrate(run):
    run = checked_work(run)
    if run.parent != WORK / "SIM-026":
        raise ValueError("Expected an owned SIM-026 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-026")
    if row["commit"] != COMMIT:
        raise ValueError("Unreviewed FlyConnectome commit")
    receipt = WORK / "SIM-026/assets/route-check.json"
    if receipt.exists() and (
        hashlib.sha256(receipt.read_bytes()).hexdigest()
        != row["access_preflight"]["sha256"]
    ):
        raise ValueError("FlyConnectome metadata acquisition receipt changed")
    info = (
        load(receipt)
        if receipt.exists()
        else {
            "checked_at": row["access_preflight"]["metadata_verified_at"],
            "routes": row["access_preflight"]["metadata"],
        }
    )
    if len(info["routes"]) != 5 or any(
        r["status"] != "available" for r in info["routes"].values()
    ):
        raise ValueError("Registered public metadata routes have not been verified")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    acquisition = acquire_metadata(receipt.parent, info["routes"])
    directory = checked_work(run / "inputs")
    directory.mkdir(exist_ok=True)
    for item in info["routes"].values():
        source = checked_work(receipt.parent / item["file"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Public metadata snapshot changed")
        target = checked_work(directory / item["file"])
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Existing run metadata changed; preserve it")
        else:
            shutil.copy2(source, target)
    save(
        run / "flyconnectome-inputs.json",
        {
            "commit": COMMIT,
            "metadata": info,
            "primary_route_receipt": receipt.relative_to(ROOT).as_posix()
            if receipt.exists()
            else None,
            "acquisition": acquisition,
            "scope": "metadata snapshot only; actual volumes, meshes and queries are checked at runtime",
        },
    )
