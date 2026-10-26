"""Restore the exact v630 CSV exports from the pinned upstream Git tree."""

import gzip
import hashlib
import os
import shutil
import subprocess
import urllib.request

COMMIT = "ee4944c03429edf857a6b10bcf98bea7dcef35b8"
NAMES = (
    "connections.csv.gz",
    "neurons.csv.gz",
    "classification.csv.gz",
    "cell_stats.csv.gz",
    "connectivity_tags.csv.gz",
    "neuropil_synapse_table.csv.gz",
)


def identity(path, expected):
    size = path.stat().st_size
    git = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024**2):
            git.update(block)
            sha.update(block)
    if git.hexdigest() != expected:
        raise ValueError("Pinned v630 Git blob mismatch: " + path.name)
    # Reading to EOF validates the gzip footer/CRC, including concatenated members.
    with gzip.open(path, "rb") as stream:
        header = stream.readline().decode("utf-8-sig").strip()
        while stream.read(1024**2):
            pass
    if not header or "," not in header:
        raise ValueError("Missing CSV header: " + path.name)
    return {
        "git_blob": expected,
        "sha256": sha.hexdigest(),
        "bytes": size,
        "csv_header": header,
        "gzip_crc_verified": True,
    }


def fetch(url, target, expected, attempts, persist, max_attempts=2):
    """Persist each request before starting it; never accept corrupt HTTP content."""
    partial = target.with_suffix(target.suffix + ".partial")
    error = None
    while len(attempts) < max_attempts:
        item = {"attempt": len(attempts) + 1, "url": url, "status": "started"}
        attempts.append(item)
        persist()
        try:
            with (
                urllib.request.urlopen(url, timeout=60) as response,
                partial.open("wb") as output,
            ):
                shutil.copyfileobj(response, output, 1024**2)
            info = identity(partial, expected)
            partial.replace(target)
            item["status"] = "verified"
            persist()
            return info
        except (OSError, ValueError, EOFError) as exc:
            error = str(exc)
            item.update(status="failed", error=error)
            partial.unlink(missing_ok=True)
            persist()
    raise ValueError("v630 route exhausted: " + (error or url))


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent.name != "SIM-017":
        raise ValueError("v630 inputs require an owned SIM-017 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-017")
    if row["commit"] != COMMIT:
        raise ValueError("Unreviewed FlyWire analysis commit")
    repository = ROOT / row["path"]
    assets = WORK / "SIM-017/assets"
    assets.mkdir(parents=True, exist_ok=True)
    ledger = assets / "requests.json"
    requests = load(ledger) if ledger.exists() else {}
    records = []
    for name in NAMES:
        entry = subprocess.check_output(
            ["git", "ls-tree", COMMIT, "--", "v630_data/" + name],
            cwd=repository,
            env=dict(os.environ, GIT_NO_LAZY_FETCH="1"),
            text=True,
            timeout=30,
        ).strip()
        fields, found = entry.split("\t")
        mode, kind, oid = fields.split()
        if mode != "100644" or kind != "blob" or found != "v630_data/" + name:
            raise ValueError("Unexpected pinned v630 Git entry")
        target = assets / name
        url = f"https://raw.githubusercontent.com/{row['repository']}/{COMMIT}/{found}"
        history = requests.setdefault(name, [])
        # The earlier route inspection consumed one HTTP request for a prefix.
        prefix = WORK / "SIM-017/input-route-preparation.json"
        if name == "connections.csv.gz" and not history and prefix.exists():
            history.append(
                {
                    "attempt": 1,
                    "url": url,
                    "status": "prefix_only_preflight",
                    "receipt": prefix.relative_to(ROOT).as_posix(),
                }
            )
            save(ledger, requests)
        if target.exists():
            info = identity(target, oid)
        else:
            info = fetch(url, target, oid, history, lambda: save(ledger, requests))
        destination = run / "source/v630_data" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, destination)
        records.append(
            dict(
                info,
                file=name,
                primary=target.relative_to(ROOT).as_posix(),
                url=url,
                destination="source/v630_data/" + name,
            )
        )
    manifest = {
        "commit": COMMIT,
        "dataset": "FlyWire v630 pinned author exports",
        "files": records,
        "requests": requests,
    }
    save(assets / "manifest.json", manifest)
    save(run / "v630-inputs.json", manifest)


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    hydrate(Path(parser.parse_args().run))
