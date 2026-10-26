"""Check convergent propagation and the actual UI; keep all runtime state disposable."""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import simctl
from inventory import ROOT, WORK, load, save
from probes.snedea_assets import hydrate, identity

ICONS = {
    "app-icon.svg": "ba55425c2fcd16767939f737baf0562ba5ba5f04",
    "center.svg": "70f4345da3fd703a6cbf5972cae36620a058c6f9",
    "claude-cursor.svg": "8459edbe2e54a93c95876ebfb109b3d5f6706e06",
    "clear.svg": "4bb8d3f7ec1d8f493c4080c31415e4f45b2ade3a",
    "github.svg": "2176ef8eb397a730d32c0ce7d171cd9b29fac819",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def icons(run):
    base = WORK / "SIM-029/assets/icons"
    base.mkdir(exist_ok=True)
    ledger = base / "requests.json"
    requests = load(ledger) if ledger.exists() else {}
    save(ledger, requests)
    records = []
    for name, oid in ICONS.items():
        primary = base / name
        url = (
            "https://raw.githubusercontent.com/snedea/flybrain/9191824d17871b7851645782d53d23f213ddb938/svg/"
            + name
        )
        attempts = requests.setdefault(name, [])
        while not primary.exists() and len(attempts) < 2:
            item = {"url": url, "attempt": len(attempts) + 1, "status": "started"}
            attempts.append(item)
            save(ledger, requests)
            partial = primary.with_suffix(".partial")
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    partial.write_bytes(response.read(1024**2))
                identity(partial, oid)
                partial.replace(primary)
                item["status"] = "verified"
            except (OSError, ValueError) as exc:
                item.update(status="failed", error=str(exc))
                partial.unlink(missing_ok=True)
            save(ledger, requests)
        if not primary.exists():
            raise ValueError("Author UI icon unavailable after two attempts")
        info = identity(primary, oid)
        destination = run / "source/svg" / name
        destination.parent.mkdir(exist_ok=True)
        if not destination.exists():
            shutil.copyfile(primary, destination)
        identity(destination, oid)
        records.append({"file": "svg/" + name, "url": url, **info})
    save(run / "ui-assets.json", {"files": records})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run = simctl.checked_work(Path(args.run))
    if run.parent != WORK / "SIM-029":
        raise ValueError("Expected an owned SIM-029 run")
    core = load(run / "result.json")
    assert core["status"] == "reproduced"
    hydrate(run)
    assert (
        sha(run / "source/js/sim-worker.js")
        == load(run / "worker-correction.json")["after_sha256"]
    )
    assert not simctl.command(
        ["docker", "ps", "-q", "--filter", "label=aspa.simulation.owner=simctl"]
    ).stdout.strip()
    extra = run / "extra-probes"
    extra.mkdir(exist_ok=True)
    module = Path(__file__).with_name("snedea_propagation.cjs")
    target = extra / (module.stem + "-" + sha(module)[:12] + module.suffix)
    shutil.copyfile(module, target)
    stage = "convergent-propagation"
    profile = {
        "image": core["profile"]["image"],
        stage: "node /work/extra-probes/" + target.name,
        "data_scope": "diagnostic convergent stimulation and zero-weight control on author export",
    }
    receipt = run / "propagation-phase.json"
    qualified = load(receipt) if receipt.exists() else None
    if (
        qualified
        and qualified["script_sha256"] == sha(target)
        and qualified["core_result_sha256"] == sha(run / "result.json")
    ):
        item = qualified["phase"]
    else:
        item = simctl.phase({"id": "SIM-029"}, profile, stage, run, core["policy"])
        if receipt.exists():
            receipt = run / ("propagation-phase-" + uuid.uuid4().hex[:10] + ".json")
        save(
            receipt,
            {
                "phase": item,
                "script_sha256": sha(target),
                "core_result_sha256": sha(run / "result.json"),
            },
        )
    if item["status"] != "passed":
        raise RuntimeError("Convergent propagation diagnostic failed")
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("snedea_plot.py")),
            "--run",
            str(run),
        ],
        check=True,
        timeout=60,
    )
    icons(run)
    review_token = uuid.uuid4().hex[:10]
    tools = run / "browser-tools"
    tools.mkdir(exist_ok=True)
    for name in ["package.json", "package-lock.json"]:
        shutil.copyfile(
            ROOT / "simulations/environments/browser-tools" / name, tools / name
        )
    tmp = run / "browser-tmp"
    tmp.mkdir(exist_ok=True)
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
    for name in ["npmrc", "npm-globalrc"]:
        (tmp / name).write_bytes(b"")
    env.update(
        TEMP=str(tmp),
        TMP=str(tmp),
        PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD="1",
        NPM_CONFIG_USERCONFIG=str(tmp / "npmrc"),
        NPM_CONFIG_GLOBALCONFIG=str(tmp / "npm-globalrc"),
    )
    command = [
        shutil.which("npm.cmd") or shutil.which("npm"),
        "ci",
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
        "--cache",
        str(run / "npm-cache"),
    ]
    started = time.monotonic()
    with (run / ("browser-install-" + review_token + ".log")).open(
        "w", encoding="utf-8"
    ) as stream:
        install = subprocess.run(
            command,
            cwd=tools,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=1800,
            check=False,
        )
    save(
        run / ("browser-install-" + review_token + ".json"),
        {
            "exit_code": install.returncode,
            "seconds": time.monotonic() - started,
            "lock_sha256": sha(tools / "package-lock.json"),
        },
    )
    if install.returncode:
        raise RuntimeError("Browser driver install failed")
    driver = Path(__file__).with_name("snedea_browser_probe.mjs")
    frozen = extra / (driver.stem + "-" + sha(driver)[:12] + driver.suffix)
    shutil.copyfile(driver, frozen)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def translate_path(self, raw):
            target = (
                run / "source" / unquote(urlsplit(raw).path).lstrip("/")
            ).resolve()
            if target.is_relative_to((run / "source").resolve()):
                return str(target)
            return str(tmp / "not-found")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env.update(
        ASPA_SNEDEA_URL=f"http://127.0.0.1:{server.server_port}",
        ASPA_SNEDEA_OUTPUT=str(run / ("exports/browser-" + review_token)),
        ASPA_SNEDEA_TOOLS=str(tools),
        ASPA_SNEDEA_PROFILE=str(run / ("browser-profile-" + review_token)),
        ASPA_SNEDEA_EDGE=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ASPA_SNEDEA_SVG=str(run / "exports/recorded-events.svg"),
        ASPA_SNEDEA_PROPAGATION_SVG=str(run / "exports/recorded-propagation.svg"),
    )
    started = time.monotonic()
    try:
        with (run / ("browser-" + review_token + ".log")).open(
            "w", encoding="utf-8"
        ) as stream:
            process = subprocess.Popen(
                [shutil.which("node"), str(frozen)],
                cwd=tools,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                code = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                code = process.wait(timeout=30)
        save(
            run / ("browser-phase-" + review_token + ".json"),
            {
                "exit_code": code,
                "seconds": time.monotonic() - started,
                "driver_sha256": sha(frozen),
                "core_result_sha256": sha(run / "result.json"),
                "server_port": server.server_port,
                "external_http_and_websockets": "blocked",
                "server_closed": True,
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
    print("Browser review finished; isolated local HTTP server closed")
    if code:
        raise RuntimeError("Browser review failed; inspect saved screenshots and logs")


if __name__ == "__main__":
    main()
