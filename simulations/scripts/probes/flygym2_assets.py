"""Restore bundled assets of the two registered FlyGym APIs by Git identity."""

import hashlib
import os
import shutil
import subprocess
import urllib.request
import zipfile

COMMIT = "38c8ec61034cd59bc5ba0de20688d4a3c0000d60"
LEGACY_COMMIT = "d285260a1c8a7b3494150cd1590f2c9fe4b5e06b"


def hydrate(run, candidate_id="SIM-020"):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    pins = {"SIM-020": COMMIT, "SIM-021": LEGACY_COMMIT}
    if candidate_id not in pins or run.parent.name != candidate_id:
        raise ValueError("FlyGym assets require an owned registered run")
    commit = pins[candidate_id]
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == candidate_id)
    if row["commit"] != commit:
        raise ValueError("Unreviewed FlyGym commit")
    assets = WORK / candidate_id / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    archive = assets / (commit + ".zip")
    url = f"https://codeload.github.com/{row['repository']}/zip/{commit}"
    receipt = assets / "archive-requests.json"
    attempts = load(receipt) if receipt.exists() else []
    if not archive.exists():
        while len(attempts) < 2:
            item = {"attempt": len(attempts) + 1, "url": url, "status": "started"}
            attempts.append(item)
            save(receipt, attempts)
            partial = archive.with_suffix(".zip.partial")
            try:
                with (
                    urllib.request.urlopen(url, timeout=60) as response,
                    partial.open("wb") as output,
                ):
                    shutil.copyfileobj(response, output, 1024**2)
                with zipfile.ZipFile(partial) as bundle:
                    if bundle.testzip() is not None:
                        raise ValueError("Invalid FlyGym archive CRC")
                partial.replace(archive)
                item["status"] = "downloaded"
                save(receipt, attempts)
                break
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                partial.unlink(missing_ok=True)
                item.update(status="failed", error=str(exc))
                save(receipt, attempts)
        if not archive.exists():
            raise ValueError("Pinned FlyGym archive unavailable after two attempts")
    tree = subprocess.check_output(
        ["git", "ls-tree", "-r", commit],
        cwd=ROOT / row["path"],
        text=True,
        timeout=30,
        env=dict(os.environ, GIT_NO_LAZY_FETCH="1"),
    )
    restored = []
    with zipfile.ZipFile(archive) as bundle:
        roots = {name.split("/")[0] for name in bundle.namelist()}
        if len(roots) != 1 or not next(iter(roots)).endswith(commit):
            raise ValueError("Unexpected FlyGym archive root")
        prefix = next(iter(roots)) + "/"
        for line in tree.splitlines():
            metadata, name = line.split("\t")
            mode, kind, oid = metadata.split()
            if mode not in {"100644", "100755"} or kind != "blob":
                continue
            package = "flygym_gymnasium/" if candidate_id == "SIM-021" else "src/"
            if not name.startswith((package, "tests/")):
                continue
            target = checked_work(run / "source" / name)
            if target.exists():
                continue
            body = bundle.read(prefix + name)
            actual = hashlib.sha1(
                b"blob " + str(len(body)).encode() + b"\0" + body
            ).hexdigest()
            if actual != oid:
                raise ValueError("Pinned FlyGym blob mismatch: " + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
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
        run / "bundled-assets.json",
        {
            "commit": commit,
            "url": url,
            "archive": archive.relative_to(ROOT).as_posix(),
            "archive_sha256": digest,
            "restored": restored,
            "scope": "pinned bundled assets; remote high-resolution S3 models not substituted",
        },
    )
