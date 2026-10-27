"""Test-only transport fault injector; never included in an application profile.

The acceptance overlay alone mounts this script and its project-owned control
volume. No host port, credentials, or configurable upstream is exposed.
"""

from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONTROL = Path("/control")
LOCK = threading.Lock()


def record(mode, path):
    with LOCK:
        target = CONTROL / "observations.json"
        data = json.loads(target.read_text()) if target.exists() else {}
        key = mode + ":" + path
        data[key] = data.get(key, 0) + 1
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(data))
        temporary.replace(target)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def answer(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self):
        if self.path == "/health":
            self.answer(200, b'{"ready":true}')
            return
        try:
            mode = json.loads((CONTROL / "fault.json").read_text()).get("mode", "none")
        except FileNotFoundError:
            mode = "none"
        if mode == "discard_outage" and self.path.endswith("/discard"):
            record(mode, self.path)
            self.answer(503, b'{"detail":"injected_discard_outage"}')
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        connection = http.client.HTTPConnection("generator", 8090, timeout=30)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
            status = response.status
            content_type = response.getheader(
                "Content-Type", "application/octet-stream"
            )
            if (
                self.command == "GET"
                and "/v1/executions/" in self.path
                and status == 200
            ):
                if "/artifacts/" not in self.path:
                    payload = json.loads(data)
                    if payload.get("status") == "completed" and mode in {
                        "missing_manifest",
                        "discard_outage",
                        "invalid_units",
                    }:
                        if mode == "invalid_units":
                            payload["manifest"]["units"]["signal"] = "mV"
                        else:
                            payload["manifest"]["files"].pop()
                        data = json.dumps(payload).encode()
                        record(mode, self.path)
                elif mode == "artifact_hash" and self.path.endswith("/signals.csv"):
                    data = data[:-1] + bytes([data[-1] ^ 1])
                    record(mode, self.path)
                elif mode == "artifact_missing" and self.path.endswith("/signals.csv"):
                    status, data = 404, b'{"detail":"injected_missing_artifact"}'
                    record(mode, self.path)
            self.answer(status, data, content_type)
        except (OSError, http.client.HTTPException):
            self.answer(502, b'{"detail":"executor_transport_unavailable"}')
        finally:
            connection.close()

    do_GET = dispatch
    do_POST = dispatch


if __name__ == "__main__":
    CONTROL.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", 8091), Handler).serve_forever()
