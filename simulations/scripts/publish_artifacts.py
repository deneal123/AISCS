"""Publish only explicitly registered visual outputs with verified source hashes."""

import argparse
import hashlib
import shutil
from pathlib import Path

from inventory import load
from paths import ARTIFACTS, REGISTRY, ROOT, WORK


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def locations(row, visual):
    name = visual["file"]
    if Path(name).name != name or "\\" in name or "/" in name or name in {".", ".."}:
        raise ValueError(f"Invalid artifact name: {name}")
    if Path(name).suffix.lower() not in {
        ".png",
        ".jpg",
        ".jpeg",
        ".pdf",
        ".mp4",
        ".svg",
        ".webm",
    }:
        raise ValueError(f"Not a visual artifact: {name}")
    source = (ROOT / visual["source"]).resolve()
    if not source.is_relative_to((WORK / row["id"]).resolve()):
        raise ValueError("Artifact source must belong to this SIM run area")
    destination = ARTIFACTS / row["id"] / name
    if not source.is_file() or digest(source) != visual["sha256"]:
        raise ValueError(f"Missing or changed source: {source}")
    return source, destination


def publish(registry, check=False):
    count = 0
    for row in registry["candidates"]:
        for visual in row.get("visual_artifacts", []):
            source, destination = locations(row, visual)
            if check:
                if not destination.is_file() or digest(destination) != visual["sha256"]:
                    raise ValueError(
                        f"Missing or changed published artifact: {destination}"
                    )
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(f"Visual artifacts checked/published: {publish(load(REGISTRY), args.check)}")


if __name__ == "__main__":
    main()
