"""Test the image's CLI, loopback HTTP and read-only non-root execution."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="aspa-research-sidecar")
    args = parser.parse_args()
    name = "aspa-research-smoke-" + uuid.uuid4().hex[:10]
    names = [name + "-cli", name]
    report = {"image": args.image, "status": "failed"}
    output = ROOT / ".work/checks"
    output.mkdir(parents=True, exist_ok=True)
    try:
        cli = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                names[0],
                args.image,
                "python",
                "-m",
                "service.cli",
                "--data-dir",
                "/data",
                "validate",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=True,
        )
        # Exit 0 alone is insufficient: an entrypoint could ignore the CLI command.
        payload = json.loads(cli.stdout)
        assert payload["ok"] is True
        report["cli_counts"] = payload["counts"]
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--read-only",
                "--tmpfs",
                "/tmp:size=32m,noexec,nosuid,nodev",
                "-p",
                "127.0.0.1::8080",
                args.image,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        port = subprocess.check_output(["docker", "port", name, "8080/tcp"], timeout=10)
        url = "http://127.0.0.1:" + port.decode().strip().rsplit(":", 1)[1]
        for _ in range(40):
            try:
                with urllib.request.urlopen(url + "/ready", timeout=2) as response:
                    ready = json.load(response)
                if ready.get("ok"):
                    break
            except OSError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("HTTP readiness was not reached")
        assert ready["counts"] == payload["counts"]
        with urllib.request.urlopen(url + "/v1/sources?limit=2", timeout=10) as response:
            assert response.status == 200
            json.load(response)
        try:
            urllib.request.urlopen(
                urllib.request.Request(url + "/v1/sources", method="POST"), timeout=5
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 405
        else:
            raise AssertionError("HTTP write was unexpectedly accepted")
        config = json.loads(subprocess.check_output(["docker", "inspect", name], timeout=10))[0]
        assert config["Config"]["User"] == "65532:65532"
        assert config["HostConfig"]["ReadonlyRootfs"] is True
        report.update(
            status="passed",
            http_ready=True,
            http_write_status=405,
            user=config["Config"]["User"],
            read_only=True,
            image_id=config["Image"],
        )
    finally:
        for owned in names:
            subprocess.run(
                ["docker", "rm", "-f", owned], capture_output=True, timeout=20, check=False
            )
        (output / "docker-smoke.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
