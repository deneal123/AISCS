"""Serve only owned source/artifact routes; keep browser state inside this run."""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulations/scripts"))
import simctl


def cpu_check(run, script_name, stage, receipt_name):
    result = simctl.load(run / "result.json")
    script = Path(__file__).with_name(script_name)
    sha = hashlib.sha256(script.read_bytes()).hexdigest()
    extra = run / "extra-probes"
    extra.mkdir(exist_ok=True)
    target = extra / (script.stem + "-" + sha[:12] + ".py")
    shutil.copyfile(script, target)
    profile = {
        "image": result["profile"]["image"],
        stage: "/work/env/bin/python -u /work/extra-probes/" + target.name,
        "data_scope": "additional fixed-point software check; no biological calibration",
    }
    item = simctl.phase({"id": "SIM-016"}, profile, stage, run, result["policy"])
    simctl.save(
        run / receipt_name,
        {
            "phase": item,
            "script": target.relative_to(ROOT).as_posix(),
            "script_sha256": sha,
        },
    )
    if item["status"] != "passed":
        raise RuntimeError(stage + " failed; see recorded receipt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", required=True, help="Owned SIM-016 run inside research/.work"
    )
    args = parser.parse_args()
    run = simctl.checked_work(Path(args.run))
    if run.parent != simctl.WORK / "SIM-016" or not (run / "result.json").is_file():
        raise ValueError("A registered SIM-016 run is required")
    source = run / "source"
    active = simctl.command(
        ["docker", "ps", "-q", "--filter", "label=aspa.simulation.owner=simctl"]
    )
    if active.returncode or active.stdout.strip():
        raise RuntimeError(
            "Do not overlap the browser GPU trial with a live simulator container"
        )
    active_receipt = run / "active-stress-phase.json"
    expected_sha = hashlib.sha256(
        Path(__file__).with_name("soup_active_probe.py").read_bytes()
    ).hexdigest()
    if (
        not active_receipt.is_file()
        or simctl.load(active_receipt).get("script_sha256") != expected_sha
        or simctl.load(active_receipt)["phase"]["status"] != "passed"
    ):
        cpu_check(run, "soup_active_probe.py", "stress", "active-stress-phase.json")
    for name in ("tmp", "browser-profile", "exports/browser"):
        (run / name).mkdir(parents=True, exist_ok=True)
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
        }
    }
    env.update(
        TEMP=str(run / "tmp"),
        TMP=str(run / "tmp"),
        PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD="1",
        PLAYWRIGHT_BROWSERS_PATH=str(run / "cache/pw"),
        NPM_CONFIG_USERCONFIG=str(run / "tmp/npmrc"),
        NPM_CONFIG_GLOBALCONFIG=str(run / "tmp/npm-globalrc"),
    )
    for name in ("npmrc", "npm-globalrc"):
        (run / "tmp" / name).write_bytes(b"")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    assert npm
    records = []
    for label, command in [
        (
            "npm-ci",
            [
                npm,
                "ci",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--cache",
                str(run / "npm-cache"),
            ],
        ),
        ("node-tests", [npm, "test"]),
    ]:
        started = time.monotonic()
        with (run / (label + ".log")).open("w", encoding="utf-8") as log:
            p = subprocess.run(
                command,
                cwd=source / "web",
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=1800,
                check=False,
            )
        records.append(
            {
                "stage": label,
                "exit_code": p.returncode,
                "seconds": time.monotonic() - started,
            }
        )
        simctl.save(run / "web-node-checks.json", {"phases": records})
        if p.returncode:
            raise RuntimeError(label + " failed; see recorded log")

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def translate_path(self, raw):
            route = unquote(urlsplit(raw).path)
            prefixes = (
                (
                    "/artifacts/male-cns-v1.0-annotated.scx/",
                    run / "cache/male-cns-v1.0-annotated.scx",
                ),
                ("/web/", source / "web"),
                ("/test/", source / "web/test"),
                ("/src/", source / "web/src"),
                ("/wasm/", source / "web/wasm"),
            )
            for prefix, base in prefixes:
                if route.startswith(prefix):
                    target = (base / route[len(prefix) :]).resolve()
                    if target.is_relative_to(base.resolve()):
                        return str(target)
            return str(run / "tmp/route-not-found")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env.update(
        ASPA_SOUP_SOURCE=str(source),
        ASPA_SOUP_OUTPUT=str(run / "exports/browser"),
        ASPA_SOUP_PROFILE=str(run / "browser-profile"),
        SOUP_CONNECTOME_E2E_EXECUTABLE=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ASPA_SOUP_BASE_URL=f"http://127.0.0.1:{server.server_port}",
    )
    command = [
        shutil.which("node"),
        str(ROOT / "simulations/scripts/probes/soup_browser_probe.mjs"),
    ]
    try:
        with (run / "browser-check.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                env=env,
                cwd=source / "web",
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                code = process.wait(timeout=900)
            except subprocess.TimeoutExpired:
                if process.poll() is None:
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=30,
                        check=False,
                    )
                code = process.wait(timeout=30)
        simctl.save(
            run / "browser-check.json",
            {
                "exit_code": code,
                "server_port": server.server_port,
                "scope": "isolated installed Edge, author fixture and full-scale pages",
                "driver_sha256": hashlib.sha256(
                    (
                        ROOT / "simulations/scripts/probes/soup_browser_probe.mjs"
                    ).read_bytes()
                ).hexdigest(),
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
    print("Browser trial complete; local server closed")
    if code:
        raise RuntimeError("Browser checks failed; see recorded results")
    cpu_check(run, "soup_cross_backend.py", "parity", "cross-backend-phase.json")


if __name__ == "__main__":
    main()
