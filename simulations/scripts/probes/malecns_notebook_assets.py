"""Acquire the v0.9 inputs selected by the pinned SIM-008 notebook, twice at most."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import REGISTRY, ROOT, WORK, load, save


def preflight_inputs(folder):
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-008")
    base = ROOT / row["path"]
    head = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=base).decode().strip()
    )
    assert head == row["commit"], "Refuse data acquisition for a changed source pin"
    notebook = base / "supplemental_data/quantify-neuron-connections.ipynb"
    content = json.loads(notebook.read_text())
    source = "\n".join(
        "".join(c["source"]) for c in content["cells"] if c["cell_type"] == "code"
    )
    version = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)", source).group(1)
    assert version == "v0.9", "A new notebook dataset version requires separate review"
    path = folder / "input-preflight-20261025.json"
    if path.exists():
        return load(path)
    inputs = []
    for stem in ("body-annotations", "connectome-weights"):
        name = f"{stem}-male-cns-{version}-minconf-0.5.feather"
        url = f"https://storage.googleapis.com/flyem-male-cns/{version}/connectome-data/flat-connectome/{name}"
        record = {"file": name, "url": url, "attempts": []}
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(url, method="HEAD"), timeout=30
                ) as response:
                    record["attempts"].append(
                        {
                            "attempt": attempt,
                            "status": response.status,
                            "content_length": response.headers["Content-Length"],
                            "google_hash": response.headers["x-goog-hash"],
                            "generation": response.headers["x-goog-generation"],
                        }
                    )
                break
            except (OSError, urllib.error.URLError) as exc:
                record["attempts"].append({"attempt": attempt, "error": str(exc)})
        record["available"] = record["attempts"][-1].get("status") == 200
        inputs.append(record)
    result = {
        "commit": row["commit"],
        "dataset": version,
        "inputs": inputs,
        "date_utc": datetime.now(UTC).isoformat(),
        "scope": "HTTP HEAD only; complete byte identity is checked after download",
    }
    save(path, result)
    return result


def main():
    folder = WORK / "SIM-008"
    folder.mkdir(parents=True, exist_ok=True)
    preflight = preflight_inputs(folder)
    target = folder / "assets"
    target.mkdir(exist_ok=True)
    manifest = folder / "v09-inputs.json"
    previous = load(manifest).get("inputs", []) if manifest.exists() else []
    records = []
    for source in preflight["inputs"]:
        header = source["attempts"][-1]
        assert source["available"] and header["status"] == 200
        name = source["file"]
        assert Path(name).name == name and "v0.9" in name
        path = target / name
        known = next((x for x in previous if x["file"] == name), None)
        if path.exists() and known:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
                    digest.update(chunk)
            if digest.hexdigest() == known["sha256"]:
                records.append(known)
                continue
        url = source["url"] + "?generation=" + header["generation"]
        partial = path.with_suffix(path.suffix + ".partial")
        errors = []
        for attempt in (1, 2):
            try:
                digest = hashlib.sha256()
                size = 0
                print(
                    f"Downloading pinned generation: {name}, attempt {attempt}",
                    flush=True,
                )
                with (
                    urllib.request.urlopen(url, timeout=60) as response,
                    partial.open("wb") as output,
                ):
                    for chunk in iter(lambda: response.read(4 * 1024**2), b""):
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                assert size == int(header["content_length"]), "Truncated source input"
                partial.replace(path)
                records.append(
                    {
                        "file": name,
                        "path": path.relative_to(ROOT).as_posix(),
                        "url": source["url"],
                        "pinned_url": url,
                        "generation": header["generation"],
                        "bytes": size,
                        "sha256": digest.hexdigest(),
                        "google_hash": header["google_hash"],
                        "attempt": attempt,
                        "prior_errors": errors,
                    }
                )
                print(
                    f"Saved {name}: {size} bytes; SHA-256 {digest.hexdigest()}",
                    flush=True,
                )
                break
            except (OSError, urllib.error.URLError, AssertionError) as exc:
                errors.append(str(exc))
                if attempt == 2:
                    save(
                        manifest,
                        {
                            "status": "blocked",
                            "inputs": records,
                            "failed_input": name,
                            "errors": errors,
                        },
                    )
                    raise
        save(
            manifest,
            {
                "status": "downloaded_pending_crc_validation",
                "inputs": records,
                "dataset": "MaleCNS v0.9",
                "source": "pinned SIM-008 notebook",
            },
        )


if __name__ == "__main__":
    main()
