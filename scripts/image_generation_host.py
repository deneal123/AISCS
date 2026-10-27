"""Запускается только с явным согласием на один платный dev-прогон."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from scripts.harness.live.host import docker, remove_source, temporary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-one-paid-image", action="store_true", required=True)
    parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    backend, agents = "gpthub-dev-backend-1", "gpthub-dev-agents-1"
    target = temporary(backend)
    source = temporary(agents)
    server = None
    try:
        docker("cp", str(root / "backend/scripts"), backend + ":" + target, timeout=30)
        docker(
            "cp",
            str(root / "agents/scripts/image_generation_live.py"),
            agents + ":" + source + "/server.py",
        )
        server = subprocess.Popen(
            ["docker", "exec", "-i", agents, "python", source + "/server.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        health = (
            "import urllib.request; "
            "assert urllib.request.urlopen('http://agents:8091/health',timeout=1).status==200"
        )
        deadline = time.monotonic() + 40
        while True:
            assert server.poll() is None, "owned_sidecar_stopped"
            try:
                docker("exec", backend, "python", "-c", health, timeout=3)
                break
            except (RuntimeError, subprocess.TimeoutExpired):
                if time.monotonic() >= deadline:
                    raise RuntimeError("owned_sidecar_not_ready") from None
                time.sleep(0.2)
        code = (
            "import runpy,sys;sys.path.insert(0,sys.argv[1]);"
            "runpy.run_module('scripts.image_generation_live',run_name='__main__')"
        )
        print(json.dumps({"stage": "isolated_sidecar_ready", "paid_image_limit": 1}), flush=True)
        process = subprocess.Popen(
            ["docker", "exec", backend, "python", "-c", code, target],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        for line in process.stdout:
            # Никаких чужих логов, payload, ключей или трассировок.
            if line.startswith('{"stage":') or line.startswith('{"job_id":'):
                print(line.strip(), flush=True)
        if process.wait() != 0:
            raise RuntimeError("paid_probe_not_verified")
    finally:
        if server is not None and server.poll() is None:
            server.stdin.close()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                print(json.dumps({"stage": "owned_sidecar_cleanup_unconfirmed"}), flush=True)
        if server is None or server.poll() is not None:
            remove_source(agents, source)
            remove_source(backend, target)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"stage": "host", "error": type(error).__name__}), flush=True)
        sys.exit(1)
