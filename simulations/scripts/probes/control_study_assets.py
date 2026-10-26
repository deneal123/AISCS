"""Restore pinned lightweight study tables, without using bundled plots as runs."""

import hashlib
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

COMMIT = "336e0d12a6edd92a7340cfffb71985a3879055ce"


def restore(archive, run, entries):
    from simctl import checked_work

    restored = []
    with zipfile.ZipFile(archive) as bundle:
        roots = {Path(name).parts[0] for name in bundle.namelist()}
        if len(roots) != 1 or not next(iter(roots)).endswith(COMMIT):
            raise ValueError("Unexpected pinned study archive root")
        prefix = next(iter(roots)) + "/"
        for name, oid in entries.items():
            target = checked_work(run / "source" / name)
            if target.exists():
                continue
            content = bundle.read(prefix + name)
            actual = hashlib.sha1(
                b"blob " + str(len(content)).encode() + b"\0" + content
            ).hexdigest()
            if actual != oid:
                raise ValueError("Pinned study blob mismatch: " + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            restored.append(
                {
                    "file": name,
                    "git_blob": oid,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    return restored


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent.name != "SIM-018":
        raise ValueError("Wrong study run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-018")
    if row["commit"] != COMMIT:
        raise ValueError("Unreviewed study commit")
    tree = subprocess.check_output(
        ["git", "ls-tree", "-r", COMMIT],
        cwd=ROOT / row["path"],
        text=True,
        timeout=30,
        env=dict(os.environ, GIT_NO_LAZY_FETCH="1"),
    )
    entries = {}
    for line in tree.splitlines():
        metadata, name = line.split("\t")
        mode, kind, oid = metadata.split()
        if (
            mode in {"100644", "100755"}
            and kind == "blob"
            and name.startswith(("data/", "results/", "configs/"))
            and Path(name).suffix in {".csv", ".json", ".yaml", ".yml"}
        ):
            entries[name] = oid
    assets = WORK / "SIM-018/assets"
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
            try:
                with (
                    urllib.request.urlopen(url, timeout=60) as response,
                    archive.open("wb") as output,
                ):
                    shutil.copyfileobj(response, output, 1024**2)
                with zipfile.ZipFile(archive) as bundle:
                    if bundle.testzip() is not None:
                        raise ValueError("Corrupt study archive")
                item["status"] = "downloaded"
                save(receipt, attempts)
                break
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                archive.unlink(missing_ok=True)
                item.update(status="failed", error=str(exc))
                save(receipt, attempts)
        if not archive.exists():
            raise ValueError("Study archive route exhausted")
    records = restore(archive, run, entries)
    with archive.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    save(
        run / "study-inputs.json",
        {
            "commit": COMMIT,
            "archive": archive.relative_to(ROOT).as_posix(),
            "url": url,
            "sha256": sha,
            "restored": records,
            "scope": "author lightweight tables, not new training results or bundled image reproduction",
        },
    )
    # Both original failures are retained in earlier run receipts. Keep these
    # packaging/path repairs explicit and outside the canonical sidecar.
    patches = []
    for name in ("revision_control_utils.py", "random_mask_utils.py"):
        module = run / "source/scripts" / name
        original = module.read_bytes()
        changed, reasons = compatibility(
            original, alias=name == "revision_control_utils.py"
        )
        module.write_bytes(changed)
        patches.append(
            {
                "file": "scripts/" + name,
                "before_sha256": hashlib.sha256(original).hexdigest(),
                "after_sha256": hashlib.sha256(changed).hexdigest(),
                "changes": reasons,
            }
        )
    save(
        run / "working-copy-compatibility.json",
        {"files": patches, "changes_model_or_data": False},
    )


def compatibility(original, alias=False):
    old = b"get_default_config(overrides=DEFAULT_CONFIG_OVERRIDES)"
    if original.count(old) != 1:
        raise ValueError("Unreviewed study configuration call")
    replacement = (
        b"get_default_config(overrides=DEFAULT_CONFIG_OVERRIDES, "
        b"path=str(Path(__import__('flyvis').__file__).resolve().parent / 'config/solver.yaml'))"
    )
    changed = original.replace(old, replacement)
    reasons = [
        "Use the same installed FlyVis solver.yaml via an explicit path; default source-tree-relative path fails in the wheel"
    ]
    if alias:
        if b"FLYVIS_REPO_ROOT =" in original:
            raise ValueError("Unreviewed study path alias")
        changed += (
            b"\n# Compatibility export required by the packaged training CLI.\n"
            b"import flyvis as _aspa_flyvis\n"
            b"FLYVIS_REPO_ROOT = Path(_aspa_flyvis.__file__).resolve().parent.parent\n"
        )
        reasons.append(
            "Export the package path required by the original fromscratch CLI"
        )
    return changed, reasons
