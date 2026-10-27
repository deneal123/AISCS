"""Real local-storage, ownership and cancellation checks in an owned test project."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx

from simulation_acceptance import Acceptance, ROOT


class LocalAcceptance(Acceptance):
    def run(self):
        deadline = time.monotonic() + 90
        while True:
            try:
                ready = self.client.get("/api/health", timeout=3).status_code == 200
            except httpx.HTTPError:
                ready = False
            if ready or time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        self.check("backend_ready_before_auth", ready)
        self.login()
        backend = self.python(
            "from service.settings import config\nprint(config.storage.backend)\n"
        )
        self.check(
            "configured_backend_is_local", backend.strip().splitlines()[-1] == "local"
        )
        first = self.create(97101, duration_ms=200.0, dt_ms=0.025)
        self.wait(first["id"], {"completed"})
        self.verify_files(first["id"])
        endpoint = "/api/simulations/v1/runs/" + first["id"]
        items = self.client.get(endpoint + "/artifacts").json()["items"]

        self.control("stop", "minio")
        self.verify_files(first["id"])
        second = self.create(97102, duration_ms=200.0, dt_ms=0.025)
        self.wait(second["id"], {"completed"})
        self.verify_files(second["id"])
        self.check("local_publication_and_download_without_minio", True)

        anonymous = httpx.get(str(self.client.base_url).rstrip("/") + endpoint)
        self.check("anonymous_run_rejected", anonymous.status_code == 401)
        owner_client = self.client
        self.client = httpx.Client(base_url="http://localhost:8096", timeout=30)
        try:
            self.login()
            for suffix in (
                "",
                "/artifacts",
                "/manifest",
                "/artifacts/" + items[0]["id"],
            ):
                response = self.client.get(endpoint + suffix)
                self.check(
                    "foreign_identity_hidden_" + (suffix or "run"),
                    response.status_code == 404,
                )
        finally:
            self.client.close()
            self.client = owner_client

        self.control("stop", "celery-worker-simulation")
        self.control("stop", "celery-beat")
        queued = self.create(97103, duration_ms=200.0, dt_ms=0.025)
        self.check(
            "queued_without_executor", self.get(queued["id"])["state"] == "queued"
        )
        response = self.client.post(
            "/api/simulations/v1/runs/" + queued["id"] + "/cancel"
        )
        self.check(
            "queued_cancelled_without_attempt",
            response.json()["state"] == "cancelled"
            and response.json()["attempt_id"] is None,
        )
        self.control("start", "celery-worker-simulation")
        self.control("start", "celery-beat")
        time.sleep(2)
        self.check(
            "redelivered_cancelled_job_never_started",
            self.attempts(queued["id"]) == []
            and self.get(queued["id"])["state"] == "cancelled",
        )

        active = self.create(97104)
        self.wait(active["id"], {"running"}, timeout=30)
        response = self.client.post(
            "/api/simulations/v1/runs/" + active["id"] + "/cancel"
        )
        self.check("running_cancel_accepted", response.status_code == 200)
        self.wait(active["id"], {"cancelled"})
        time.sleep(1)
        self.check(
            "running_cancel_remains_terminal",
            self.get(active["id"])["state"] == "cancelled",
        )

        self.control("stop", "postgres")
        try:
            for suffix in (
                "",
                "/artifacts",
                "/manifest",
                "/artifacts/" + items[0]["id"],
            ):
                response = self.client.get(endpoint + suffix)
                self.check(
                    "database_failure_denies_result_" + (suffix or "run"),
                    response.status_code >= 500,
                )
        finally:
            self.control("start", "postgres")
        self.report["passed"] = True

    def restore(self):
        super().restore()
        for service in ("postgres", "celery-beat"):
            try:
                self.control("start", service)
            except Exception:
                self.report.setdefault("restore_errors", []).append(service)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="aspa-acceptance-local")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".work/generator-implementation/local-storage-acceptance.json",
    )
    args = parser.parse_args()
    runner = LocalAcceptance(args.project, args.output)
    try:
        runner.run()
    except Exception as error:
        runner.report.update(passed=False, error_type=type(error).__name__)
        if isinstance(error, RuntimeError):
            runner.report["error_code"] = str(error)
        print("acceptance_failed=" + type(error).__name__, flush=True)
    finally:
        runner.restore()
        runner.save()
        runner.client.close()
    return 0 if runner.report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
