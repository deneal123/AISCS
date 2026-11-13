"""Pack verified selected-cell currents for transfer without unsafe ZIP extraction."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

from service.infrastructure.stimulation.recording.current_archive import _sha, _stream_sha


def _manifest(payload: bytes, expected_sha: str):
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha):
        raise ValueError("Trusted current manifest digest required")
    if _sha(payload) != expected_sha:
        raise ValueError("Current manifest checksum mismatch")
    manifest = json.loads(payload)
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != "selected-current-archive-v1"
        or not isinstance(manifest.get("cells"), list)
        or not manifest["cells"]
    ):
        raise ValueError("Invalid current manifest")
    for index, entry in enumerate(manifest["cells"]):
        if (
            not isinstance(entry, dict)
            or entry.get("file") != f"cell-{index:06d}.npz"
            or type(entry.get("bytes")) is not int
            or entry["bytes"] <= 0
            or not isinstance(entry.get("sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])
        ):
            raise ValueError("Invalid current manifest entry")
    return manifest


def pack_current_archive(directory: Path, manifest_sha: str, target: Path) -> dict:
    """Stream verified members into a new uncompressed ZIP; never overwrite."""
    payload = (directory / "manifest.json").read_bytes()
    manifest = _manifest(payload, manifest_sha)
    if target.resolve() == directory.resolve() or directory.resolve() in target.resolve().parents:
        raise ValueError("Transport must be outside the current archive directory")
    with target.open("xb") as output, zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as package:
        for entry in manifest["cells"]:
            path = directory / entry["file"]
            if path.stat().st_size != entry["bytes"]:
                raise ValueError("Current archive file size mismatch")
            with path.open("rb") as source:
                if _stream_sha(source) != entry["sha256"]:
                    raise ValueError("Current archive file checksum mismatch")
                source.seek(0)
                with package.open(entry["file"], "w", force_zip64=True) as destination:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        destination.write(chunk)
                if _stream_sha(source) != entry["sha256"]:
                    raise ValueError("Current archive changed while packing")
        package.writestr("manifest.json", payload)
    with target.open("rb") as stream:
        digest = _stream_sha(stream)
    return {"bytes": target.stat().st_size, "sha256": digest, "manifest_sha256": manifest_sha}


def unpack_current_archive(
    package_path: Path, package_sha: str, manifest_sha: str, destination: Path
):
    """Restore only exact declared filenames into a newly created directory."""
    if not isinstance(package_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", package_sha):
        raise ValueError("Trusted package digest required")
    if (
        destination.resolve() == package_path.resolve()
        or destination.resolve() in package_path.resolve().parents
    ):
        raise ValueError("Package and destination must be separate")
    with package_path.open("rb") as stream:
        if _stream_sha(stream) != package_sha:
            raise ValueError("Current package checksum mismatch")
        stream.seek(0)
        with zipfile.ZipFile(stream, "r") as package:
            infos = package.infolist()
            if (
                any(info.is_dir() or info.compress_type != zipfile.ZIP_STORED for info in infos)
                or sum(info.filename == "manifest.json" for info in infos) != 1
            ):
                raise ValueError("Invalid current package contents")
            payload = package.read("manifest.json")
            manifest = _manifest(payload, manifest_sha)
            expected = {"manifest.json", *(entry["file"] for entry in manifest["cells"])}
            if len(infos) != len(expected) or {info.filename for info in infos} != expected:
                raise ValueError("Unexpected or duplicate current package members")
            destination.mkdir(parents=True, exist_ok=False)
            for entry in manifest["cells"]:
                info = package.getinfo(entry["file"])
                if info.file_size != entry["bytes"] or info.compress_size != info.file_size:
                    raise ValueError("Current package member size mismatch")
                digest, total = hashlib.sha256(), 0
                with (
                    package.open(info) as source,
                    (destination / entry["file"]).open("xb") as output,
                ):
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        if output.write(chunk) != len(chunk):
                            raise OSError("Incomplete current archive restoration")
                        digest.update(chunk)
                        total += len(chunk)
                if total != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                    raise ValueError("Current package member checksum mismatch")
        if _stream_sha(stream) != package_sha:
            raise ValueError("Current package changed during restoration")
    with (destination / "manifest.json").open("xb") as output:
        if output.write(payload) != len(payload):
            raise OSError("Incomplete current manifest restoration")
