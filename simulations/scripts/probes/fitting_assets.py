"""Stage the exact author-provided archive; never replace it with synthetic FlyWire data."""

import hashlib
import shutil
import subprocess
from pathlib import Path

ARCHIVE_SHA256 = "77f3ec0c5a860a4ccdd3c9a1defc5bc336da2ae32df3cd9700abe711c60fea8c"
FILES = {
    "Completeness_630_final.csv": 3057613,
    "Connectivity_630_final.parquet": 86630944,
    "630_connections_processed.csv": 240898267,
    "spike_rates/ito_2017-10-26_1_spike_rate.npz": 3444060,
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent != WORK / "SIM-002":
        raise ValueError("Expected an owned SIM-002 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-002")
    base = checked_work(WORK / "SIM-002/assets")
    archive = base / "author-data.rar"
    if not archive.is_file() or sha(archive) != ARCHIVE_SHA256:
        raise ValueError(
            "Exact author RAR5 archive required: registered Drive file 1TPuHJ-IC1yQtL5TMngAjGJa_JAMdusnu; keep the two-attempt download ledger, no substituted data"
        )
    receipt = base / "author-inputs.json"
    existing = load(receipt) if receipt.exists() else None
    if existing and existing["archive_sha256"] != ARCHIVE_SHA256:
        raise ValueError("Author archive version changed")
    expected = {x["member"]: x for x in existing["inputs"]} if existing else {}
    extractor = shutil.which("7zz") or shutil.which("7z")
    if not extractor and Path("C:/Program Files/7-Zip/7z.exe").is_file():
        extractor = "C:/Program Files/7-Zip/7z.exe"
    inputs = []
    for name, size in FILES.items():
        primary = checked_work(base / "author" / name)
        primary.parent.mkdir(parents=True, exist_ok=True)
        if not primary.exists() or name not in expected:
            if not extractor:
                raise ValueError("A RAR5-capable 7z/7zz extractor is required")
            partial = primary.with_suffix(primary.suffix + ".partial")
            # Streaming one exact named member avoids archive-path traversal,
            # symbolic links and extraction of unrelated datasets.
            with partial.open("wb") as stream:
                process = subprocess.run(
                    [extractor, "x", "-so", str(archive), name],
                    stdin=subprocess.DEVNULL,
                    stdout=stream,
                    stderr=subprocess.PIPE,
                    timeout=600,
                    check=False,
                )
            if process.returncode or partial.stat().st_size != size:
                partial.unlink(missing_ok=True)
                raise ValueError("Author RAR member/CRC extraction failed: " + name)
            if primary.exists():
                if sha(primary) != sha(partial):
                    raise ValueError(
                        "Preserve unqualified existing author input: " + name
                    )
                partial.unlink()
            else:
                partial.replace(primary)
        digest = sha(primary)
        if (
            primary.stat().st_size != size
            or name in expected
            and expected[name]["sha256"] != digest
        ):
            raise ValueError("Preserve changed author input: " + name)
        target = checked_work(run / "source/data" / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and sha(target) != digest:
            raise ValueError("Preserve changed fitting work input: " + name)
        shutil.copyfile(primary, target)
        inputs.append(
            {
                "member": name,
                "bytes": size,
                "sha256": digest,
                "primary": primary.relative_to(ROOT).as_posix(),
                "work_file": target.relative_to(run).as_posix(),
            }
        )
        save(receipt, {"archive_sha256": ARCHIVE_SHA256, "inputs": inputs})
    lock = ROOT / "simulations/environments/fitting-cpu.lock.txt"
    shutil.copyfile(lock, base / "fitting-cpu.lock.txt")
    save(
        run / "author-inputs.json",
        {
            "commit": row["commit"],
            "archive": archive.relative_to(ROOT).as_posix(),
            "archive_sha256": ARCHIVE_SHA256,
            "received_at": "2026-10-26",
            "version_limit": "Author's Drive archive is not linked to a release tag; this exact SHA pins the actually tested input version",
            "inputs": inputs,
            "environment_lock_sha256": sha(lock),
        },
    )
