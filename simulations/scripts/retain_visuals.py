"""Retain explicitly selected native-test visuals before disposable-state cleanup."""

import argparse
import hashlib
import shutil
from pathlib import Path

from inventory import load, save
from paths import WORK

EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".mp4", ".webm"}


def retain(run, relative):
    run = run.resolve()
    if not run.is_relative_to(WORK.resolve()) or run.parent.parent != WORK.resolve():
        raise ValueError("Expected a direct owned SIM run")
    result = load(run / "result.json")
    if result.get("status") not in {"reproduced", "partial", "blocked"}:
        raise ValueError("Expected a terminal run receipt")
    source = (run / relative).resolve()
    if source == run or not source.is_relative_to(run):
        raise ValueError("Selected output directory must be inside the run")
    if not any(source.is_relative_to(run / name) for name in ("tmp", "pytest-tmp")):
        raise ValueError("Select a temporary native-test output directory")
    if not source.is_dir():
        raise ValueError("Selected native-test output directory is missing")
    target = run / "exports/native-tests"
    target.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        if not path.resolve().is_relative_to(source) or path.is_symlink():
            raise ValueError("Refusing a visual outside the selected source")
        member = path.relative_to(source).as_posix()
        name = (
            "native-"
            + hashlib.sha256(member.encode()).hexdigest()[:10]
            + "-"
            + path.name
        )
        destination = target / name
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if destination.exists():
            with destination.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError("Retained visual changed; preserve previous copy")
        else:
            shutil.copyfile(path, destination)
        with destination.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == digest
        entries.append(
            {
                "original": path.relative_to(run).as_posix(),
                "retained": destination.relative_to(run).as_posix(),
                "file": name,
                "bytes": path.stat().st_size,
                "sha256": digest,
                "scope": "native-test output; no automatic scientific acceptance",
            }
        )
    save(run / "native-visuals.json", {"source": relative, "files": entries})
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--from", dest="source", required=True)
    args = parser.parse_args()
    from cleanup import running_mounts

    run = args.run.resolve()
    if any(
        m == run or m.is_relative_to(run) or run.is_relative_to(m)
        for m in running_mounts()
    ):
        raise ValueError("Wait for the owned run to finish before retaining outputs")
    print("Retained native visuals:", len(retain(run, args.source)))


if __name__ == "__main__":
    main()
