"""Restore exact claude-fly blobs and bounded, hash-checked primary LFS assets."""

import hashlib
import re
import shutil
import time
import urllib.request
from pathlib import Path

COMMIT = "3a035275148e97539711728422548bffe2a77566"
PARQUET = "d386555d1a5f40ebfa1380bcb05b1fab044855fd"
COMPLETENESS = "b5a26b82b69a3c2e7fd99cd6810c36fc8f0e492b"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save

    run = Path(run).resolve()
    if not run.is_relative_to(WORK.resolve()) or run.parent.name != "SIM-015":
        raise ValueError("claude-fly inputs require an owned SIM-015 run")
    preparation = load(WORK / "SIM-015/input-routes-preparation.json")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-015")
    missing = {}
    if row.get("frozen_inputs"):
        reference = row["frozen_inputs"]
        manifest = (ROOT / reference["path"]).resolve()
        if (
            not manifest.is_relative_to((WORK / "SIM-015").resolve())
            or sha(manifest) != reference["sha256"]
        ):
            raise ValueError("Frozen claude-fly manifest changed")
        previous = load(manifest)
        if previous["commit"] != COMMIT:
            raise ValueError("Frozen claude-fly commit mismatch")
        missing = {
            x["path"]: x for x in previous["inputs"] if x.get("status") == "unavailable"
        }
    data = run / "source/data"
    data.mkdir(parents=True, exist_ok=True)
    records = []
    for name, source_key, expected in (
        ("2025_Connectivity_783.parquet", "connectivity_primary", PARQUET),
        ("2025_Completeness_783.csv", "source_completeness", COMPLETENESS),
    ):
        source = (ROOT / preparation[source_key]).resolve()
        if not source.is_relative_to((WORK / "SIM-006").resolve()):
            raise ValueError("Primary reuse path escaped the registered SIM-006 area")
        raw = source.read_bytes()
        if name.endswith(".csv"):
            if (
                hashlib.sha256(raw).hexdigest()
                != preparation["source_completeness_sha256"]
            ):
                raise ValueError("Retained primary completeness changed")
            derived = raw.replace(b"\r\n", b"\n")
            transformation = "CRLF to LF only; exact target Git blob verified"
        else:
            derived = raw
            transformation = "byte-for-byte reuse"
        if blob(derived) != expected:
            raise ValueError("Pinned Git blob mismatch: " + name)
        target = data / name
        target.write_bytes(derived)
        records.append(
            {
                "path": "data/" + name,
                "git_blob": expected,
                "bytes": len(derived),
                "sha256": sha(target),
                "primary": source.relative_to(ROOT).as_posix(),
                "primary_sha256": sha(source),
                "transformation": transformation,
                "network_attempts": 0,
            }
        )
    assets = WORK / "SIM-015/assets"
    assets.mkdir(exist_ok=True)
    attempts = []
    for pointer in preparation["pointers"]:
        name = pointer["name"]
        if Path(name).name != name:
            raise ValueError("Invalid LFS asset name")
        expected = re.search(r"oid sha256:([a-f0-9]{64})", pointer["body"]).group(1)
        size = int(re.search(r"size (\d+)", pointer["body"]).group(1))
        primary = assets / name
        url = (
            "https://media.githubusercontent.com/media/legacyindiesubmissions-ai/"
            "claude-fly/" + COMMIT + "/data/" + name
        )
        if "data/" + name in missing:
            item = missing["data/" + name]
            if (
                item["sha256"] != expected
                or item["bytes"] != size
                or item["url"] != url
            ):
                raise ValueError("Frozen unavailable LFS pointer changed")
            records.append(
                dict(item, reuse="terminal unavailable state; no new network attempts")
            )
            continue
        for attempt in range(1, 3):
            if (
                primary.is_file()
                and primary.stat().st_size == size
                and sha(primary) == expected
            ):
                break
            partial = primary.with_suffix(".partial")
            started = time.monotonic()
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "Aspa-SIM-evaluation"}
                )
                with (
                    urllib.request.urlopen(request, timeout=60) as response,
                    partial.open("wb") as out,
                ):
                    shutil.copyfileobj(response, out)
                if partial.stat().st_size != size or sha(partial) != expected:
                    raise ValueError("LFS content does not match the pinned pointer")
                partial.replace(primary)
                attempts.append(
                    {
                        "name": name,
                        "attempt": attempt,
                        "url": url,
                        "status": "passed",
                        "seconds": time.monotonic() - started,
                    }
                )
            except (OSError, ValueError) as exc:
                attempts.append(
                    {
                        "name": name,
                        "attempt": attempt,
                        "url": url,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
            finally:
                partial.unlink(missing_ok=True)
                save(run / "lfs-downloads.json", {"attempts": attempts})
        if (
            not primary.is_file()
            or primary.stat().st_size != size
            or sha(primary) != expected
        ):
            records.append(
                {
                    "path": "data/" + name,
                    "status": "unavailable",
                    "sha256": expected,
                    "bytes": size,
                    "url": url,
                }
            )
            continue
        shutil.copyfile(primary, data / name)
        records.append(
            {
                "path": "data/" + name,
                "status": "verified",
                "sha256": expected,
                "bytes": size,
                "url": url,
                "primary": primary.relative_to(ROOT).as_posix(),
                "transformation": "byte-for-byte LFS content",
            }
        )
    save(
        run / "claude-inputs.json",
        {
            "commit": COMMIT,
            "version": "FlyWire v783",
            "inputs": records,
            "attempts": attempts,
        },
    )
    print("claude-fly inputs restored with exact blob/LFS identity", flush=True)
