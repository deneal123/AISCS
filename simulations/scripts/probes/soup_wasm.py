"""Run the optional Rust/WASM checks after the CPU trial is terminal."""

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulations/scripts"))
import simctl

TOOL = {
    "name": "wasm-pack-v0.15.0-x86_64-unknown-linux-musl.tar.gz",
    "size": 2881231,
    "browser_download_url": "https://github.com/wasm-bindgen/wasm-pack/releases/download/v0.15.0/wasm-pack-v0.15.0-x86_64-unknown-linux-musl.tar.gz",
    "digest": "sha256:c09f971ecaed9a2efc80fdcea7a00ef6b53c7fadc8c57d1f61b53a6aa66b668a",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", required=True, help="Owned SIM-016 run inside research/.work"
    )
    args = parser.parse_args()
    run = simctl.checked_work(Path(args.run))
    if run.parent != simctl.WORK / "SIM-016" or not (run / "result.json").is_file():
        raise ValueError("A registered SIM-016 run is required")
    active = simctl.command(
        ["docker", "ps", "-q", "--filter", "label=aspa.simulation.owner=simctl"]
    )
    if active.returncode or active.stdout.strip():
        raise RuntimeError(
            "A simulator container is live or its state is unknown; do not overlap builds"
        )
    asset = TOOL
    archive = run.parent / "assets" / asset["name"]
    if not archive.is_file():
        archive.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(
                    asset["browser_download_url"], timeout=60
                ) as response:
                    content = response.read(asset["size"] + 1)
                if (
                    len(content) != asset["size"]
                    or "sha256:" + hashlib.sha256(content).hexdigest()
                    != asset["digest"]
                ):
                    raise ValueError("Pinned wasm-pack bytes changed")
                archive.write_bytes(content)
                break
            except OSError:
                if attempt == 2:
                    raise
    assert (
        "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest() == asset["digest"]
    )
    tools = run / "cache/wasm-tools"
    tools.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = [
            m
            for m in tar.getmembers()
            if m.isfile() and Path(m.name).name == "wasm-pack"
        ]
        assert len(members) == 1
        with (
            tar.extractfile(members[0]) as source,
            (tools / "wasm-pack").open("wb") as target,
        ):
            shutil.copyfileobj(source, target)
    profile = {
        "image": "rust:1.91.1-slim@sha256:eebf495b1e54a2fbe843b2a90524fe5a93bbcac1bba4cd587e420040d808fd04",
        "data_scope": "Rust unit tests and WASM build only, not a neural simulation",
        "install": (
            "export CARGO_HOME=/work/cache/cargo CARGO_TARGET_DIR=/work/cache/rust-target CARGO_BUILD_JOBS=4; "
            "chmod +x /work/cache/wasm-tools/wasm-pack; "
            "rustc --version > /work/rust-version.txt; cargo --version > /work/cargo-version.txt; "
            "rustup target add wasm32-unknown-unknown; "
            "cargo test --locked --manifest-path /work/source/web/wasm/Cargo.toml; "
            "/work/cache/wasm-tools/wasm-pack build /work/source/web/wasm --target web "
            "--out-dir /work/source/web/wasm/pkg --release --no-opt --locked"
        ),
    }
    before = simctl.command(["docker", "image", "inspect", profile["image"]])
    result = {
        "scope": profile["data_scope"],
        "profile": profile,
        "image_present_before": before.returncode == 0,
        "phases": [],
        "tool": asset,
    }
    simctl.save(run / "wasm-build-check.json", dict(result, status="running"))
    if before.returncode == 0:
        result["image_id_before"] = json.loads(before.stdout)[0]["Id"]
    policy = json.loads((run / "result.json").read_text())["policy"]
    item = simctl.phase({"id": "SIM-016"}, profile, "install", run, policy)
    result["phases"].append(item)
    result["status"] = item["status"]
    after = simctl.command(["docker", "image", "inspect", profile["image"]])
    if after.returncode == 0:
        result["image_id_after"] = json.loads(after.stdout)[0]["Id"]
        result["repo_digests"] = json.loads(after.stdout)[0].get("RepoDigests")
    pkg = run / "source/web/wasm/pkg"
    result["build_outputs"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in pkg.glob("*")
        if p.is_file()
    }
    simctl.save(run / "wasm-build-check.json", result)
    print(
        json.dumps(
            {"status": result["status"], "outputs": list(result["build_outputs"])},
            indent=2,
        )
    )
    if result["status"] != "passed":
        raise RuntimeError("Rust/WASM checks failed; see recorded results")


if __name__ == "__main__":
    main()
