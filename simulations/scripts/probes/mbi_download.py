"""Recover only the reviewed OSF release; persistent two-attempt acquisition."""

import hashlib
import json
import time
import urllib.request
from pathlib import Path

from inventory import ROOT, WORK, load, save
from simctl import checked_work

CATALOG = "https://api.osf.io/v2/nodes/9hxwe/files/osfstorage/"
IDENTITY = "e7bc30df6d3e67477b8f45568829acdefca64b2aa51ba433612083de9c409bd4"


def catalog_identity(files):
    body = [
        {key: item[key] for key in ("id", "path", "bytes", "version", "sha256")}
        for item in sorted(files, key=lambda item: item["path"])
    ]
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_catalog(base):
    target = base / "file-inventory.json"
    if target.exists():
        result = load(target)
    else:
        pages = base / "catalog-pages"
        pages.mkdir(parents=True, exist_ok=True)
        todo, seen, files, errors = [CATALOG], set(), [], []
        while todo:
            url = todo.pop(0)
            if url in seen:
                continue
            if not url.startswith(CATALOG):
                raise ValueError("Unexpected OSF catalog route")
            seen.add(url)
            page = pages / (hashlib.sha256(url.encode()).hexdigest() + ".json")
            receipt = page.with_name(page.stem + "-requests.json")
            attempts = load(receipt)["attempts"] if receipt.exists() else []
            while not page.exists() and len(attempts) < 2:
                attempt = {"attempt": len(attempts) + 1, "status": "started"}
                attempts.append(attempt)
                save(receipt, {"url": url, "attempts": attempts})
                try:
                    request = urllib.request.Request(
                        url, headers={"Accept": "application/vnd.api+json"}
                    )
                    with urllib.request.urlopen(request, timeout=30) as response:
                        data = json.load(response)
                    save(page, data)
                    attempt["status"] = "read"
                except (OSError, ValueError) as exc:
                    attempt.update(status="failed", error=str(exc))
                save(receipt, {"url": url, "attempts": attempts})
            if not page.exists():
                errors.append(url)
                continue
            data = load(page)
            for item in data["data"]:
                a = item["attributes"]
                if a["kind"] == "folder":
                    todo.append(
                        item["relationships"]["files"]["links"]["related"]["href"]
                    )
                else:
                    files.append(
                        {
                            "id": item["id"],
                            "path": a["materialized_path"].lstrip("/"),
                            "bytes": a["size"],
                            "version": a["current_version"],
                            "sha256": a["extra"]["hashes"]["sha256"],
                            "modified": a["date_modified"],
                            "download": item["links"]["download"],
                            "info": item["links"]["info"],
                        }
                    )
            if data.get("links", {}).get("next"):
                todo.append(data["links"]["next"])
        result = {
            "project": "9hxwe",
            "pages": sorted(seen),
            "files": files,
            "errors": errors,
        }
        save(target, result)
    if result["errors"] or catalog_identity(result["files"]) != IDENTITY:
        raise ValueError("OSF catalog differs from the reviewed 72-file release")
    return result


def acquire():
    base = checked_work(WORK / "SIM-025/assets")
    base.mkdir(parents=True, exist_ok=True)
    catalog = read_catalog(base)
    ledger = base / "download-requests.json"
    requests = load(ledger) if ledger.exists() else {}
    files, errors = [], []
    for item in sorted(catalog["files"], key=lambda item: item["bytes"]):
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe OSF filename")
        path = checked_work(base / "data" / relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        attempts = requests.setdefault(item["id"], [])
        if path.exists():
            with path.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            if sha != item["sha256"] or path.stat().st_size != item["bytes"]:
                raise ValueError(
                    "Existing primary differs; preserve it: " + item["path"]
                )
        while not path.exists() and len(attempts) < 2:
            record = {
                "attempt": len(attempts) + 1,
                "url": item["download"],
                "version": item["version"],
                "status": "started",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            attempts.append(record)
            save(ledger, requests)
            partial = path.with_name(path.name + ".partial")
            try:
                sha, size = hashlib.sha256(), 0
                with (
                    urllib.request.urlopen(item["download"], timeout=60) as response,
                    partial.open("wb") as stream,
                ):
                    for chunk in iter(lambda: response.read(1024**2), b""):
                        stream.write(chunk)
                        sha.update(chunk)
                        size += len(chunk)
                if size != item["bytes"] or sha.hexdigest() != item["sha256"]:
                    raise ValueError("OSF primary size or hash mismatch")
                partial.replace(path)
                record.update(status="verified", bytes=size, sha256=sha.hexdigest())
            except (OSError, ValueError) as exc:
                partial.unlink(missing_ok=True)
                record.update(status="failed", error=str(exc))
            save(ledger, requests)
        if path.exists():
            files.append(
                {
                    **item,
                    "primary": path.relative_to(ROOT).as_posix(),
                    "status": "verified",
                }
            )
        else:
            errors.append(item["path"])
        save(
            base / "inputs.json",
            {
                "project": "9hxwe",
                "files": files,
                "errors": errors,
                "catalog_files": len(catalog["files"]),
                "complete": len(files) + len(errors) == len(catalog["files"]),
            },
        )
    if errors:
        raise ValueError("Registered OSF inputs unavailable after two attempts")
    return load(base / "inputs.json")
