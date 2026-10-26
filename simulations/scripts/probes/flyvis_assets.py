"""Exact optic-lobe specification and official checksum-pinned pretrained ensemble."""

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import PurePosixPath

COMMIT = "92b3845cc426dd309a1a0e1b3890156c42e14021"
FILES = {
    "flyvis/connectome/fib25-fib19_v2.2.json": "3e2bafee4b53c34ede54261c990f1c688d854ba6",
    "flyvis/data/responses_norm.h5": "272919f5201899bdca226d675e4a542f85e4a5f7",
    "flyvis/analysis/visualization/matplotlibrc": "083c8292f6cdc9f10623611112dcb693b2157a1b",
}
ARCHIVE_SHA256 = "71c78d4070556a536b13b23ee3139cd2788aa2a9d07d430a223b4edead281db1"


def identity(path, oid):
    size = path.stat().st_size
    blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            blob.update(chunk)
            sha.update(chunk)
    if blob.hexdigest() != oid:
        raise ValueError("Flyvis pinned Git input differs: " + path.name)
    return {"bytes": size, "git_blob": oid, "sha256": sha.hexdigest()}


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent != WORK / "SIM-031":
        raise ValueError("Expected an owned SIM-031 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-031")
    if row["commit"] != COMMIT:
        raise ValueError("Unreviewed Flyvis revision")
    base = WORK / "SIM-031/assets"
    base.mkdir(parents=True, exist_ok=True)
    ledger = base / "requests.json"
    records = load(ledger) if ledger.exists() else {}
    save(ledger, records)
    inputs = []
    normalizations = []
    for name, oid in FILES.items():
        primary = base / PurePosixPath(name).name
        url = f"https://raw.githubusercontent.com/TuragaLab/flyvis/{COMMIT}/{name}"
        attempts = records.setdefault(name, [])
        while not primary.exists() and len(attempts) < 2:
            record = {"attempt": len(attempts) + 1, "url": url, "status": "started"}
            attempts.append(record)
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
                record.update(status="verified", **info)
            except (OSError, ValueError) as exc:
                record.update(status="failed", error=str(exc))
                partial.unlink(missing_ok=True)
            save(ledger, records)
        if not primary.exists():
            raise ValueError("Pinned Flyvis data unavailable after two attempts")
        info = identity(primary, oid)
        target = checked_work(run / "source" / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != primary.read_bytes():
            before, after = target.read_bytes(), primary.read_bytes()
            if not name.endswith(".json") or before.replace(
                b"\r\n", b"\n"
            ) != after.replace(b"\r\n", b"\n"):
                raise ValueError("Preserve changed Flyvis working input")
            normalizations.append(
                {
                    "file": name,
                    "before_sha256": hashlib.sha256(before).hexdigest(),
                    "after_sha256": info["sha256"],
                    "change": "restore exact Git JSON bytes instead of checkout CRLF conversion",
                }
            )
        shutil.copyfile(primary, target)
        inputs.append(
            {
                "file": name,
                "url": url,
                "primary": primary.relative_to(ROOT).as_posix(),
                **info,
            }
        )
    archive = WORK / "SIM-019/assets/results_pretrained_models.zip"
    if (
        not archive.is_file()
        or hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256
    ):
        raise ValueError(
            "Acquire the exact official pretrained archive; no replacement checkpoints"
        )
    # The same checksum is declared in this pinned source's own official downloader.
    if (
        ARCHIVE_SHA256
        not in (run / "source/flyvis_cli/download_pretrained_models.py").read_text()
    ):
        raise ValueError("Official downloader checksum differs")
    extracted = []
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            path = PurePosixPath(entry.filename)
            if entry.is_dir():
                continue
            if path.is_absolute() or ".." in path.parts or path.parts[0] != "results":
                raise ValueError("Unconfined pretrained archive entry")
            data = bundle.read(entry)
            target = checked_work(run / "assets/pretrained" / path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            extracted.append(
                {
                    "member": entry.filename,
                    "destination": target.relative_to(run).as_posix(),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    models = sorted(
        {
            x["member"].split("/")[3]
            for x in extracted
            if x["member"].startswith("results/flow/0000/")
            and x["member"].endswith("/chkpts/chkpt_00000")
        }
    )
    if len(models) != 50:
        raise ValueError("Expected the original 50 pretrained models")
    save(
        run / "flyvis-inputs.json",
        {
            "commit": COMMIT,
            "inputs": inputs,
            "normalizations": normalizations,
            "archive": archive.relative_to(ROOT).as_posix(),
            "archive_sha256": ARCHIVE_SHA256,
            "models": models,
            "pretrained_files": extracted,
        },
    )
