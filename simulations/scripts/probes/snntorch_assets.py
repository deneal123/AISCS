"""Recover the registered port's two exact FlyWire inputs, not another release."""

import hashlib
import os
import shutil
import subprocess
import urllib.request
import zipfile

COMMIT = "fe55fb0cff275a2b6b54926524c8d831838e32fc"
FILES = (
    "data/2023_03_23_completeness_630_final.csv",
    "data/2023_03_23_connectivity_630_final.parquet",
)


def restore(archive, run, expected):
    from simctl import checked_work

    entries = []
    with zipfile.ZipFile(archive) as bundle:
        prefix = "fly-brain-snntorch-" + COMMIT + "/"
        for name, oid in expected.items():
            target = checked_work(run / "source" / name)
            if not target.is_relative_to((run / "source").resolve()):
                raise ValueError("Input escapes the working source")
            body = bundle.read(prefix + name)
            actual = hashlib.sha1(
                b"blob " + str(len(body)).encode() + b"\0" + body
            ).hexdigest()
            if actual != oid:
                raise ValueError("Pinned snnTorch input blob mismatch: " + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != body:
                raise ValueError("Existing working input differs from pinned data")
            target.write_bytes(body)
            entries.append(
                {
                    "file": name,
                    "git_blob": oid,
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
    return entries


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent.name != "SIM-022":
        raise ValueError("Expected an owned SIM-022 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-022")
    if row["commit"] != COMMIT:
        raise ValueError("Unreviewed snnTorch source commit")
    assets = WORK / "SIM-022/assets"
    assets.mkdir(parents=True, exist_ok=True)
    archive = assets / (COMMIT + ".zip")
    url = f"https://codeload.github.com/{row['repository']}/zip/{COMMIT}"
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
                    partial.open("wb") as stream,
                ):
                    shutil.copyfileobj(response, stream, 1024**2)
                with zipfile.ZipFile(partial) as bundle:
                    if bundle.testzip() is not None:
                        raise ValueError("Invalid snnTorch archive CRC")
                partial.replace(archive)
                item["status"] = "downloaded"
                save(receipt, attempts)
                break
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                partial.unlink(missing_ok=True)
                item.update(status="failed", error=str(exc))
                save(receipt, attempts)
        if not archive.exists():
            raise ValueError("Pinned snnTorch archive unavailable after two attempts")
    tree = subprocess.check_output(
        ["git", "ls-tree", "-r", COMMIT, "--", *FILES],
        cwd=ROOT / row["path"],
        text=True,
        timeout=30,
        env=dict(os.environ, GIT_NO_LAZY_FETCH="1"),
    )
    expected = {}
    for line in tree.splitlines():
        metadata, name = line.split("\t")
        mode, kind, oid = metadata.split()
        if mode not in {"100644", "100755"} or kind != "blob" or name not in FILES:
            raise ValueError("Unexpected snnTorch input tree entry")
        expected[name] = oid
    if set(expected) != set(FILES):
        raise ValueError("Incomplete pinned snnTorch data tree")
    entries = restore(archive, run, expected)
    code = run / "source/fly_brain.py"
    original = code.read_bytes()
    old = b"stimulated_sensory_neurons = torch.tensor(sensory_neurons_indexes, device=device)"
    new = b"stimulated_sensory_neurons = torch.tensor(sensory_neurons_indexes, device=device, dtype=torch.long)"
    if original.count(old) != 1:
        raise ValueError("Unreviewed sensory-index construction")
    fixed = original.replace(old, new)
    code.write_bytes(fixed)
    save(
        run / "compatibility.json",
        {
            "file": "fly_brain.py",
            "before_sha256": hashlib.sha256(original).hexdigest(),
            "after_sha256": hashlib.sha256(fixed).hexdigest(),
            "old": old.decode(),
            "new": new.decode(),
            "reason": "Empty sensory-index lists otherwise infer float and fail indexing; explicit long index dtype only",
            "canonical_sidecar_modified": False,
        },
    )
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    save(
        run / "pinned-assets.json",
        {
            "commit": COMMIT,
            "url": url,
            "archive": archive.relative_to(ROOT).as_posix(),
            "archive_sha256": digest,
            "files": entries,
            "scope": "exact port inputs; no alternative graph or fabricated weights",
        },
    )
