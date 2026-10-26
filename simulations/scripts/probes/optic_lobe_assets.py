"""Fetch only the Codex v783 files declared by the pinned OpticLobe sources."""

import gzip
import hashlib
import io
import os
import re
import shutil
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from inventory import REGISTRY, ROOT, load, save


def prepare_font(run):
    """Use an installed host font for headless labels, without distributing it."""
    installed = os.environ.get("ASPA_SIM_FONT_FILE")
    if not installed and os.name == "nt":
        installed = str(
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
        )
    if not installed or not Path(installed).is_file():
        return  # A Linux caller can supply a font or use its system fonts.
    directory = run / "home/fonts"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / Path(installed).name
    shutil.copy2(installed, target)
    (run / "fontconfig.conf").write_text(
        '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">'
        "<fontconfig><dir>/work/home/fonts</dir><cachedir>/work/home/fontcache</cachedir></fontconfig>\n",
        encoding="utf-8",
        newline="\n",
    )
    save(
        run / "font-provenance.json",
        {
            "source": installed,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "scope": "installed font used locally for rendering only; temporary copy removed with home/",
        },
    )


def reuse_inputs(run, reference, expected_files):
    """Replay the accepted bytes; never silently replace them with a newer export."""
    from simctl import checked_work

    manifest = checked_work(ROOT / reference["path"])
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != reference["sha256"]:
        raise ValueError("Frozen Codex manifest hash mismatch")
    receipt = load(manifest)
    if {item["file"] for item in receipt["inputs"]} != expected_files:
        raise ValueError("Frozen Codex file set mismatch")
    for item in receipt["inputs"]:
        source = checked_work(manifest.parent / item["file"])
        target = checked_work(run / item["file"])
        if (
            item["status"] != "verified"
            or hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("Frozen Codex input hash mismatch: " + item["file"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    receipt["reuse"] = {
        "date": datetime.now(UTC).isoformat(),
        "manifest": reference["path"],
        "sha256": reference["sha256"],
        "network_attempts": 0,
    }
    save(run / "codex-inputs.json", receipt)


def hydrate(run):
    from probes.infinite_sugar_assets import hydrate as restore_git

    restore_git(run, candidate_id="SIM-010")
    prepare_font(run)
    text = (run / "source/src/codexdependencies.jl").read_text(encoding="utf-8")
    base = re.search(r'DOWNLOADS = "(https://[^"]+)"', text)[1]
    entries = re.findall(
        r'register\(DataDep\("([^"]+)",.*?joinpath\(DOWNLOADS, "([^"]+)"\),(.*?)\)\s*\)\s*;',
        text,
        flags=re.DOTALL,
    )
    assert len(entries) == 8, "Unexpected upstream data registration"
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-010")
    if row.get("frozen_inputs"):
        expected = {
            "data/" + name + "/" + filename
            for name, filename, _ in entries
            if "Buhmann" not in name
        }
        reuse_inputs(run, row["frozen_inputs"], expected)
        return
    receipt = {"date": datetime.now(UTC).isoformat(), "inputs": []}
    for name, filename, tail in entries:
        if "Buhmann" in name:
            continue  # Do not mix two synapse versions in the default profile.
        target = run / "data" / name / filename
        expected = re.search(r'\(md5, "([a-f0-9]+)"\)', tail)
        item = {
            "name": name,
            "file": target.relative_to(run).as_posix(),
            "url": base + "/" + filename,
        }
        item["upstream_md5"] = expected[1] if expected else None
        target.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (1, 2):
            item["attempts"] = attempt
            partial = target.with_suffix(".partial")
            try:
                req = urllib.request.Request(
                    item["url"], headers={"User-Agent": "Aspa-SIM-010-evaluation"}
                )
                with (
                    urllib.request.urlopen(req, timeout=120) as response,
                    partial.open("wb") as out,
                ):
                    item["last_modified"] = response.headers.get("Last-Modified")
                    item["etag"] = response.headers.get("ETag")
                    item["content_length"] = response.headers.get("Content-Length")
                    item["gcs_hash"] = response.headers.get("x-goog-hash")
                    while block := response.read(1024**2):
                        out.write(block)
                content = partial.read_bytes()
                if item["content_length"] and len(content) != int(
                    item["content_length"]
                ):
                    raise ValueError("Incomplete Codex download: " + filename)
                if not content.startswith(b"\x1f\x8b"):
                    raise ValueError(
                        "Expected gzip data, not a web/error page: " + filename
                    )
                with gzip.GzipFile(fileobj=io.BytesIO(content)) as compressed:
                    header = compressed.readline(8192).decode("utf-8").strip()
                    while compressed.read(4 * 1024**2):
                        pass  # Read to EOF to verify the gzip CRC, not just the header.
                if "root_id" not in header.split(
                    ","
                ) and "pre_root_id" not in header.split(","):
                    raise ValueError("Unexpected Codex CSV header: " + filename)
                item["csv_header"] = header
                item["sha256"] = hashlib.sha256(content).hexdigest()
                item["bytes"] = len(content)
                if expected and hashlib.md5(content).hexdigest() != expected[1]:
                    raise ValueError("Registered upstream MD5 mismatch: " + filename)
                partial.replace(target)
                item["status"] = "verified"
                item.pop("error", None)
                break
            except (OSError, ValueError, EOFError) as exc:
                partial.unlink(missing_ok=True)
                item["status"] = "unavailable"
                item["error"] = str(exc)
        receipt["inputs"].append(item)
        save(run / "codex-inputs.json", receipt)
        print("SIM-010 input", filename, item["status"], flush=True)
        if item["status"] != "verified":
            raise ValueError("Pinned Codex input unavailable: " + filename)
