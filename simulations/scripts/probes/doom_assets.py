"""Restore omitted source resources from the exact registered DOOMFLY commit."""

import hashlib
import os
import shutil
import subprocess
import urllib.request
import zipfile

COMMIT = "71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33"


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent.name != "SIM-023":
        raise ValueError("Expected an owned SIM-023 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-023")
    if row["commit"] != COMMIT:
        raise ValueError("Unreviewed DOOMFLY source")
    assets = WORK / "SIM-023/assets"
    assets.mkdir(parents=True, exist_ok=True)
    archive = assets / (COMMIT + ".zip")
    url = f"https://codeload.github.com/{row['repository']}/zip/{COMMIT}"
    requests = assets / "archive-requests.json"
    attempts = load(requests) if requests.exists() else []
    if not archive.exists():
        while len(attempts) < 2:
            item = {"attempt": len(attempts) + 1, "url": url, "status": "started"}
            attempts.append(item)
            save(requests, attempts)
            partial = archive.with_suffix(".zip.partial")
            try:
                with (
                    urllib.request.urlopen(url, timeout=60) as response,
                    partial.open("wb") as stream,
                ):
                    shutil.copyfileobj(response, stream, 1024**2)
                with zipfile.ZipFile(partial) as bundle:
                    if bundle.testzip() is not None:
                        raise ValueError("Invalid DOOMFLY archive CRC")
                partial.replace(archive)
                item["status"] = "downloaded"
                save(requests, attempts)
                break
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                partial.unlink(missing_ok=True)
                item.update(status="failed", error=str(exc))
                save(requests, attempts)
        if not archive.exists():
            raise ValueError("Pinned DOOMFLY archive unavailable after two attempts")
    tree = subprocess.check_output(
        ["git", "ls-tree", "-r", COMMIT],
        cwd=ROOT / row["path"],
        text=True,
        timeout=30,
        env=dict(os.environ, GIT_NO_LAZY_FETCH="1"),
    )
    restored = []
    with zipfile.ZipFile(archive) as bundle:
        prefix = "doomfly-" + COMMIT + "/"
        for line in tree.splitlines():
            metadata, name = line.split("\t")
            mode, kind, oid = metadata.split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                continue
            path = checked_work(run / "source" / name)
            if not path.is_relative_to((run / "source").resolve()):
                raise ValueError("DOOMFLY archive member escapes source")
            if path.exists():
                continue
            body = bundle.read(prefix + name)
            actual = hashlib.sha1(
                b"blob " + str(len(body)).encode() + b"\0" + body
            ).hexdigest()
            if actual != oid:
                raise ValueError("Pinned DOOMFLY blob mismatch: " + name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            restored.append(
                {
                    "file": name,
                    "git_blob": oid,
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    save(
        run / "pinned-source.json",
        {
            "commit": COMMIT,
            "url": url,
            "archive": archive.relative_to(ROOT).as_posix(),
            "archive_sha256": digest,
            "restored": restored,
            "scope": "exact released source resources; no downloaded graph, weights or fabricated game outcomes",
        },
    )
    prepare_inputs(run)


def prepare_inputs(run):
    """Reuse only byte-identical registered MaleCNS inputs, without redownload."""
    from inventory import ROOT, WORK, load, save
    from simctl import checked_work

    source = checked_work(run / "source")
    lock_path = source / "data-provenance/malecns_v1/source.lock.json"
    lock = load(lock_path)
    config = load(source / "doom/datasets.json")["datasets"]["malecns_v1"]
    original = WORK / "SIM-001/20261005T105111Z-6999dc/connectome/raw"
    target = source / "connectome_data/malecns_v1"
    target.mkdir(parents=True, exist_ok=True)
    inputs = []
    for name, info in lock.items():
        if config["files"].get(name) != info["url"]:
            raise ValueError("DOOMFLY dataset route and pinned lock disagree")
        raw = checked_work(original / info["url"].rsplit("/", 1)[1])
        if not raw.is_file() or raw.stat().st_size != info["bytes"]:
            raise ValueError("Registered MaleCNS primary input missing: " + name)
        with raw.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != info["sha256"]:
            raise ValueError("Registered MaleCNS primary SHA-256 mismatch: " + name)
        destination = checked_work(target / name)
        if destination.exists():
            with destination.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != digest:
                raise ValueError("Existing DOOMFLY input differs: " + name)
        else:
            shutil.copy2(raw, destination)
        inputs.append(
            {"name": name, **info, "reused_from": raw.relative_to(ROOT).as_posix()}
        )
    shutil.copy2(lock_path, target / "source.lock.json")
    save(run / "input-identity.json", {"commit": COMMIT, "inputs": inputs})
