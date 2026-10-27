"""Real fault checks against an isolated aspa-acceptance Compose project.

Run with the backend environment. Only explicitly labelled acceptance containers
may be interrupted. Secrets and OTP remain in memory; diagnostics contain states.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


class Acceptance:
    def __init__(self, project: str, output: Path):
        if not re.fullmatch(r"aspa-acceptance(?:-[a-z0-9]+)?", project):
            raise ValueError("Only an isolated aspa-acceptance project is supported")
        self.project, self.output = project, output
        self.client = httpx.Client(base_url="http://localhost:8096", timeout=30)
        self.report = {"project": project, "checks": [], "runs": [], "production_started": False}

    def check(self, name, condition, **details):
        self.report["checks"].append({"name": name, "passed": bool(condition), **details})
        self.save()
        print(name + ": " + ("PASS" if condition else "FAIL"), flush=True)
        if not condition:
            raise RuntimeError(name)

    def save(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(self.report, indent=2) + "\n", encoding="utf-8")

    def name(self, service):
        return self.project + "-" + service + "-1"

    def docker(self, *args, input=None, timeout=40):
        result = subprocess.run(
            ["docker", *args],
            input=input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError("owned_docker_command_failed:" + args[0])
        return result.stdout

    def control(self, action, service):
        name = self.name(service)
        record = json.loads(self.docker("inspect", name))[0]
        if record["Config"]["Labels"].get("com.docker.compose.project") != self.project:
            raise RuntimeError("container_ownership_mismatch")
        self.docker(action, name)

    def python(self, code):
        return self.docker("exec", "-i", self.name("backend"), "python", "-", input=code)

    def login(self):
        email = "simulation-faults-" + uuid4().hex[:8] + "@example.com"
        password = "Local9-" + secrets.token_urlsafe(20)
        source = (ROOT / "backend/scripts/create_dev_user.py").read_text(encoding="utf-8")
        code = source.replace(
            "    main()\n", "    sys.argv=" + repr(["-", email, password]) + "\n    main()\n"
        )
        self.python(code)
        response = self.client.post(
            "/api/auth/v1/login", json={"email": email, "password": password}
        )
        self.check("login", response.status_code == 200)
        otp = None
        for _ in range(30):
            messages = httpx.get("http://localhost:8028/api/v1/messages").json().get("messages", [])
            for message in messages:
                if not any(item.get("Address") == email for item in message.get("To", [])):
                    continue
                detail = httpx.get("http://localhost:8028/api/v1/message/" + message["ID"]).json()
                found = re.search(r"(?<!\d)(\d{6})(?!\d)", detail.get("Text", ""))
                if found:
                    otp = found.group(1)
                    break
            if otp:
                break
            time.sleep(0.2)
        self.check("local_otp_available", otp is not None)
        response = self.client.post("/api/auth/v1/verify", json={"email": email, "code": otp})
        self.check("verified_owner_session", response.status_code == 200)

    def get(self, run_id):
        response = self.client.get("/api/simulations/v1/runs/" + run_id)
        response.raise_for_status()
        return response.json()

    def create(self, seed, **overrides):
        config = {
            "seed": seed,
            "stimulus": "strong",
            "duration_ms": 1000.0,
            "dt_ms": 0.0125,
            **overrides,
        }
        request = {
            "request_id": str(uuid4()),
            "title": "Fault acceptance " + str(seed),
            "configuration": config,
        }
        response = self.client.post("/api/simulations/v1/runs", json=request)
        response.raise_for_status()
        run = response.json()
        self.report["runs"].append({"id": run["id"], "seed": seed})
        self.save()
        return run

    def wait(self, run_id, states, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.get(run_id)
            if run["state"] in states:
                return run
            if run["state"] in {"failed", "cancelled"}:
                raise RuntimeError("unexpected_terminal_state:" + run["state"])
            time.sleep(0.08)
        self.report["observed_run"] = {k: v for k, v in self.get(run_id).items() if k != "result"}
        self.save()
        raise RuntimeError("acceptance_observation_timeout")

    def attempts(self, run_id):
        code = """import asyncio,json
from uuid import UUID
from sqlalchemy import select
from service.infrastructure.database.postgresql import PgConnector
from service.settings import config
from service.services.simulations.models import SimulationAttempt
async def main():
 connector=PgConnector(config.pg)
 try:
  async with connector.get_session_context() as session:
   query=select(SimulationAttempt).where(SimulationAttempt.run_id==UUID(RUN_ID))
   rows=(await session.execute(query.order_by(SimulationAttempt.number))).scalars().all()
   print(json.dumps([{"id":str(x.id),"number":x.number,"state":x.state} for x in rows]))
 finally: await connector.close()
asyncio.run(main())
""".replace("RUN_ID", repr(run_id))
        return json.loads(self.python(code).strip().splitlines()[-1])

    def verify_files(self, run_id):
        endpoint = "/api/simulations/v1/runs/" + run_id
        manifest_response = self.client.get(endpoint + "/manifest")
        manifest_response.raise_for_status()
        manifest = manifest_response.json()
        items = self.client.get(endpoint + "/artifacts").json()["items"]
        import hashlib

        checksums = {item["name"]: item["sha256"] for item in manifest["files"]}
        for item in items:
            response = self.client.get(endpoint + "/artifacts/" + item["id"])
            response.raise_for_status()
            if hashlib.sha256(response.content).hexdigest() != checksums[item["name"]]:
                raise RuntimeError("artifact_hash_mismatch")
        self.check("independent_export_" + run_id, len(items) == 10)

    def run(self):
        deadline = time.monotonic() + 90
        while True:
            try:
                ready = self.client.get("/api/health", timeout=3).status_code == 200
            except httpx.HTTPError:
                ready = False
            if ready or time.monotonic() >= deadline:
                break
            time.sleep(.5)
        self.check("backend_ready_before_auth", ready)
        self.login()
        first = self.create(97001, duration_ms=200.0, dt_ms=0.025)
        self.python(
            "from service.services.simulations.tasks import execute_run\n"
            + "execute_run.apply_async(args=["
            + repr(first["id"])
            + "], queue='simulation')\n"
        )
        done = self.wait(first["id"], {"completed"})
        self.check("duplicate_queue_delivery_one_attempt", len(self.attempts(first["id"])) == 1)
        self.verify_files(first["id"])
        moved = self.create(
            97001,
            duration_ms=200.0,
            dt_ms=0.025,
            placement={"electrode": {"x_um": 0, "y_um": 170, "z_um": 40}},
        )
        moved_done = self.wait(moved["id"], {"completed"})
        old_cache = done["result"]["manifest"]["dynamics_cache"]
        new_cache = moved_done["result"]["manifest"]["dynamics_cache"]
        self.check(
            "same_currents_new_electrode",
            new_cache["status"] == "hit" and old_cache["data_sha256"] == new_cache["data_sha256"],
        )
        self.check(
            "recording_changed",
            done["result"]["preview"]["signal_uv"] != moved_done["result"]["preview"]["signal_uv"],
        )

        worker_run = self.create(97002)
        running = self.wait(worker_run["id"], {"running"}, timeout=30)
        before = running["attempt_id"]
        self.control("kill", "celery-worker-simulation")
        self.control("start", "celery-worker-simulation")
        recovered = self.wait(worker_run["id"], {"completed"})
        self.check(
            "worker_reconnects_to_known_attempt",
            recovered["attempt_id"] == before
            and len(self.attempts(worker_run["id"])) == 1
            and recovered["error"] is None,
        )
        self.verify_files(worker_run["id"])

        interrupted = self.create(97003)
        running = self.wait(interrupted["id"], {"running"}, timeout=30)
        self.control("kill", "generator")
        self.control("start", "generator")
        recovered = self.wait(interrupted["id"], {"completed"})
        history = self.attempts(interrupted["id"])
        self.check(
            "generator_interruption_new_attempt",
            recovered["attempt_id"] != running["attempt_id"]
            and len(history) == 2
            and history[0]["state"] == "interrupted",
        )
        self.verify_files(interrupted["id"])

        self.control("stop", "redis")
        self.check(
            "durable_result_read_without_redis", self.get(first["id"])["state"] == "completed"
        )
        payload = {
            "request_id": str(uuid4()),
            "title": "Redis outbox acceptance",
            "configuration": {"seed": 97004, "duration_ms": 100.0},
        }
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.client.post, "/api/simulations/v1/runs", json=payload)
            saved = None
            for _ in range(50):
                rows = self.client.get("/api/simulations/v1/runs").json()["items"]
                saved = next((row for row in rows if row["title"] == payload["title"]), None)
                if saved:
                    break
                time.sleep(0.1)
            self.check("outbox_exists_before_broker_recovery", saved is not None)
            self.control("start", "redis")
            try:
                pending.result(timeout=40)
            except httpx.TimeoutException:
                pass
        done = self.wait(saved["id"], {"completed"})
        repeated = self.client.post("/api/simulations/v1/runs", json=payload)
        self.check(
            "lost_response_reuses_durable_run",
            repeated.status_code == 201 and repeated.json()["id"] == saved["id"],
        )

        cancelled = self.create(97005)
        self.wait(cancelled["id"], {"running"}, timeout=30)
        self.control("pause", "minio")
        self.wait(cancelled["id"], {"publishing"}, timeout=30)
        response = self.client.post("/api/simulations/v1/runs/" + cancelled["id"] + "/cancel")
        self.check("cancel_during_publication_accepted", response.status_code == 200)
        self.control("unpause", "minio")
        terminal = self.wait(cancelled["id"], {"cancelled"})
        time.sleep(1)
        self.check(
            "late_publication_never_success", self.get(terminal["id"])["state"] == "cancelled"
        )
        self.report["passed"] = True

    def restore(self):
        for service in ("redis", "minio", "generator", "celery-worker-simulation"):
            try:
                record = json.loads(self.docker("inspect", self.name(service)))[0]
                if record["State"].get("Paused"):
                    self.control("unpause", service)
                if not record["State"]["Running"]:
                    self.control("start", service)
            except Exception:
                self.report.setdefault("restore_errors", []).append(service)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="aspa-acceptance")
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".work/generator-implementation/runtime-faults.json"
    )
    args = parser.parse_args()
    runner = Acceptance(args.project, args.output)
    try:
        runner.run()
    except Exception as exc:
        runner.report.update(passed=False, error_type=type(exc).__name__)
        if isinstance(exc, RuntimeError):
            runner.report["error_code"] = str(exc)
        print("acceptance_failed=" + type(exc).__name__, flush=True)
    finally:
        runner.restore()
        runner.save()
        runner.client.close()
    return 0 if runner.report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
