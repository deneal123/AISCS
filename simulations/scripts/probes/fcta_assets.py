"""Recover the complete pinned verification bundle, never invent the withheld pipeline."""

import hashlib
import os
import shutil
import subprocess
import urllib.request
from pathlib import PurePosixPath

COMMIT = "af8e451d9010294c185b966c953616b212f0294c"
REPOSITORY = "Stavros963/fcta"


def identity(path, oid):
    size = path.stat().st_size
    blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            blob.update(chunk)
            sha.update(chunk)
    if blob.hexdigest() != oid:
        raise ValueError("FCTA pinned Git blob differs: " + path.name)
    return {"bytes": size, "git_blob": oid, "sha256": sha.hexdigest()}


def pinned_tree(sidecar):
    tree = subprocess.check_output(
        ["git", "ls-tree", "-r", COMMIT],
        cwd=sidecar,
        env=dict(os.environ, GIT_NO_LAZY_FETCH="1"),
        text=True,
        timeout=30,
    )
    files = {}
    for line in tree.splitlines():
        attributes, name = line.split("\t")
        mode, kind, oid = attributes.split()
        path = PurePosixPath(name)
        if (
            mode != "100644"
            or kind != "blob"
            or path.is_absolute()
            or ".." in path.parts
        ):
            raise ValueError("Expected regular relative files in pinned FCTA bundle")
        files[name] = oid
    if len(files) != 31 or "MANIFEST.sha256" not in files:
        raise ValueError("Unreviewed FCTA tree")
    return files


def acquire():
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-030")
    if row["commit"] != COMMIT or row["repository"] != REPOSITORY:
        raise ValueError("Unreviewed FCTA revision")
    files = pinned_tree(ROOT / row["path"])
    base = checked_work(WORK / "SIM-030/assets")
    bundle = base / "bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    ledger = base / "requests.json"
    records = load(ledger) if ledger.exists() else {}
    save(ledger, records)
    inputs = []
    for name, oid in files.items():
        primary = checked_work(bundle / name)
        primary.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/{name}"
        attempts = records.setdefault(name, [])
        bootstrap = base / "MANIFEST.sha256"
        if name == "MANIFEST.sha256" and not primary.exists() and bootstrap.exists():
            info = identity(bootstrap, oid)
            shutil.copyfile(bootstrap, primary)
            if not attempts:
                attempts.append(
                    {"attempt": 1, "url": url, "status": "verified_bootstrap", **info}
                )
                save(ledger, records)
        while not primary.exists() and len(attempts) < 2:
            attempt = {"attempt": len(attempts) + 1, "url": url, "status": "started"}
            attempts.append(attempt)
            save(ledger, records)
            partial = primary.with_suffix(primary.suffix + ".partial")
            try:
                with (
                    urllib.request.urlopen(url, timeout=60) as response,
                    partial.open("wb") as stream,
                ):
                    shutil.copyfileobj(response, stream, 1024**2)
                info = identity(partial, oid)
                partial.replace(primary)
                attempt.update(status="verified", **info)
            except (OSError, ValueError) as exc:
                attempt.update(status="failed", error=str(exc))
                partial.unlink(missing_ok=True)
            save(ledger, records)
        if not primary.exists():
            raise ValueError("Pinned FCTA file unavailable after two attempts: " + name)
        inputs.append(
            {
                "file": name,
                "url": url,
                "primary": primary.relative_to(ROOT).as_posix(),
                **identity(primary, oid),
            }
        )
    result = {"commit": COMMIT, "repository": REPOSITORY, "inputs": inputs}
    save(base / "bundle-identity.json", result)
    return result


def hydrate(run):
    from inventory import ROOT, WORK, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent != WORK / "SIM-030":
        raise ValueError("Expected an owned SIM-030 run")
    result = acquire()
    replacements = []
    for item in result["inputs"]:
        primary = ROOT / item["primary"]
        destination = checked_work(run / "source" / item["file"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (
            destination.exists()
            and hashlib.sha256(destination.read_bytes()).hexdigest() != item["sha256"]
        ):
            before, after = destination.read_bytes(), primary.read_bytes()
            if before.replace(b"\r\n", b"\n") != after.replace(b"\r\n", b"\n"):
                raise ValueError("Preserve changed FCTA working file: " + item["file"])
            replacements.append(
                {
                    "file": item["file"],
                    "before_sha256": hashlib.sha256(before).hexdigest(),
                    "after_sha256": item["sha256"],
                    "change": "restore exact pinned Git bytes instead of checkout CRLF conversion",
                }
            )
        shutil.copyfile(primary, destination)
        identity(destination, item["git_blob"])
    save(run / "fcta-inputs.json", result)
    save(
        run / "git-byte-restoration.json",
        {"replacements": replacements, "upstream_sidecar": "unchanged"},
    )
