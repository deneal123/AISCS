"""Network-level A08/A10/A13 checks in the owned fault-injection project."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from simulation_acceptance import ROOT, Acceptance


class SafetyAcceptance(Acceptance):
    def mode(self, mode):
        container = json.loads(
            self.docker("inspect", self.name("generator-fault-proxy"))
        )[0]
        if (
            container["Config"]["Labels"].get("com.docker.compose.project")
            != self.project
        ):
            raise RuntimeError("container_ownership_mismatch")
        self.docker(
            "exec",
            "-i",
            self.name("generator-fault-proxy"),
            "python",
            "-",
            input="from pathlib import Path\nimport json\n"
            + "p=Path('/control/fault.tmp');p.write_text(json.dumps({'mode': "
            + repr(mode)
            + "}));p.replace('/control/fault.json')\n",
        )

    def scratch_exists(self, attempt):
        output = self.docker(
            "exec",
            self.name("generator"),
            "python",
            "-c",
            "from pathlib import Path; print((Path('/work')/"
            + repr(attempt)
            + "/'output').exists())",
        )
        return output.strip() == "True"

    def cleared(self, run_id):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            run = self.get(run_id)
            if not (run.get("result") or {}).get("executor_discard_pending", False):
                return run
            time.sleep(0.2)
        raise RuntimeError("discard_observation_timeout")

    def failed_output(self, mode, seed):
        self.mode(mode)
        run = self.create(seed, duration_ms=200.0, dt_ms=0.025)
        failed = self.wait(run["id"], {"failed", "completed"})
        self.check(
            mode + "_not_published",
            failed["state"] == "failed"
            and failed["error"].startswith("invalid_executor_manifest:"),
        )
        response = self.client.get(
            "/api/simulations/v1/runs/" + run["id"] + "/manifest"
        )
        self.check(mode + "_manifest_unavailable", response.status_code == 409)
        return failed

    async def sockets(self, run_id):
        endpoint = "ws://localhost:8096/api/simulations/v1/runs/" + run_id + "/events"
        cookie = "auth_token=" + self.client.cookies.get("auth_token")
        options = dict(
            origin="http://localhost:8095",
            additional_headers={"Cookie": cookie},
            proxy=None,
            max_size=8 * 1024 * 1024,
        )

        async def collect(socket):
            ids, states = [], []
            async with asyncio.timeout(90):
                while True:
                    message = json.loads(await socket.recv())
                    if "event" in message:
                        ids.append(message["id"])
                        states.append(message["event"]["state"])
                    if (
                        message.get("type") == "snapshot"
                        and message["run"]["state"] == "completed"
                        and "completed" in states
                    ):
                        return ids, states, message["run"]

        async with (
            connect(endpoint, **options) as first,
            connect(endpoint, **options) as second,
        ):
            for service in (
                "celery-worker-simulation",
                "celery-worker-maintenance",
                "celery-beat",
            ):
                await asyncio.to_thread(self.control, "start", service)
            a, b = await asyncio.gather(collect(first), collect(second))
        expected = {"queued", "preparing", "running", "publishing", "completed"}
        self.check(
            "two_tabs_receive_complete_states",
            expected <= set(a[1]) and expected <= set(b[1]),
            states=a[1],
        )
        self.check(
            "two_tabs_receive_same_unique_events",
            a[0] == b[0] and len(a[0]) == len(set(a[0])),
        )
        self.check(
            "two_tabs_same_scientific_record",
            all(
                a[2]["result"][key] == b[2]["result"][key]
                for key in ("manifest", "preview")
            ),
        )
        async with connect(endpoint, **options) as reconnected:
            again = await collect(reconnected)
        self.check(
            "reconnect_recovers_without_new_calculation",
            again[0] == a[0] and len(self.attempts(run_id)) == 1,
        )

        code = """import asyncio
from service.composition.infra import build_infra
from service.settings import config
async def main():
 infra=build_infra(config)
 try: await infra.redis_client.xtrim(STREAM, maxlen=0, approximate=False)
 finally:
  await infra.redis_client.aclose()
  await infra.pg_connector.close()
asyncio.run(main())
""".replace("STREAM", repr("simulation:" + run_id + ":events"))
        await asyncio.to_thread(self.python, code)
        async with connect(endpoint, **options) as trimmed:
            async with asyncio.timeout(10):
                snapshot = json.loads(await trimmed.recv())
        self.check(
            "trimmed_history_recovers_from_durable_snapshot",
            snapshot.get("type") == "snapshot"
            and snapshot["run"]["state"] == "completed"
            and snapshot["run"]["result"]["preview"] == a[2]["result"]["preview"],
        )
        try:
            async with connect(
                endpoint, **{**options, "origin": "https://untrusted.example"}
            ):
                raise RuntimeError("untrusted_origin_accepted")
        except InvalidStatus as error:
            self.check(
                "untrusted_websocket_origin_denied", error.response.status_code == 403
            )
        try:
            async with connect(endpoint, origin="http://localhost:8095", proxy=None):
                raise RuntimeError("anonymous_websocket_accepted")
        except InvalidStatus as error:
            self.check("anonymous_websocket_denied", error.response.status_code == 403)
        other = Acceptance(
            self.project, self.output.with_name("safety-other-user.json")
        )
        try:
            await asyncio.to_thread(other.login)
            foreign = {
                **options,
                "additional_headers": {
                    "Cookie": "auth_token=" + other.client.cookies.get("auth_token")
                },
            }
            try:
                async with connect(endpoint, **foreign):
                    raise RuntimeError("foreign_websocket_accepted")
            except InvalidStatus as error:
                self.check(
                    "foreign_websocket_denied", error.response.status_code == 403
                )
        finally:
            other.client.close()
        async with connect(endpoint, **options) as lost_database:
            await lost_database.recv()
            try:
                await asyncio.to_thread(self.control, "stop", "postgres")
                async with asyncio.timeout(30):
                    while True:
                        await lost_database.recv()
            except ConnectionClosed as error:
                self.check(
                    "websocket_fails_closed_after_database_loss", error.code == 1011
                )
            finally:
                await asyncio.to_thread(self.control, "start", "postgres")

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
        self.mode("none")
        first = self.create(98200, duration_ms=200.0, dt_ms=0.025)
        self.wait(first["id"], {"completed"})
        self.verify_files(first["id"])
        self.report["minio_source_image"] = self.docker(
            "inspect", "--format", "{{.Config.Image}}", self.name("minio")
        ).strip()
        self.check(
            "pinned_source_minio_serves_real_artifacts",
            self.report["minio_source_image"].startswith("aspa-minio-source:"),
        )
        for number, mode in enumerate(
            ("missing_manifest", "invalid_units", "artifact_hash", "artifact_missing"),
            start=98201,
        ):
            failed = self.failed_output(mode, number)
            self.cleared(failed["id"])
            self.check(
                mode + "_scratch_removed", not self.scratch_exists(failed["attempt_id"])
            )
        failed = self.failed_output("discard_outage", 98205)
        self.check(
            "cleanup_intent_survives_transport_failure",
            failed["result"]["executor_discard_pending"] is True
            and self.scratch_exists(failed["attempt_id"]),
        )
        self.mode("none")
        self.python(
            "from service.services.simulations.tasks import recover_runs\nrecover_runs()\n"
        )
        cleared = self.cleared(failed["id"])
        self.check(
            "maintenance_retries_failed_cleanup",
            cleared["state"] == "failed"
            and not self.scratch_exists(failed["attempt_id"]),
        )
        self.verify_files(first["id"])
        for service in (
            "celery-worker-simulation",
            "celery-worker-maintenance",
            "celery-beat",
        ):
            self.control("stop", service)
        queued = self.create(98206, duration_ms=200.0, dt_ms=0.025)
        self.check("events_fixture_queued", queued["state"] == "queued")
        asyncio.run(self.sockets(queued["id"]))
        self.verify_files(queued["id"])
        self.report["injected_faults"] = json.loads(
            self.docker(
                "exec",
                self.name("generator-fault-proxy"),
                "python",
                "-c",
                "from pathlib import Path; print(Path('/control/observations.json').read_text())",
            )
        )
        self.report["passed"] = True
        self.save()

    def restore(self):
        super().restore()
        for service in ("postgres", "celery-worker-maintenance", "celery-beat"):
            try:
                self.control("start", service)
            except Exception:
                self.report.setdefault("restore_errors", []).append(service)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="aspa-acceptance-safety")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".work/generator-implementation/safety-acceptance.json",
    )
    args = parser.parse_args()
    runner = SafetyAcceptance(args.project, args.output)
    try:
        runner.run()
    except Exception as error:
        runner.report.update(passed=False, error_type=type(error).__name__)
        if isinstance(error, RuntimeError):
            runner.report["error_code"] = str(error)
        print("acceptance_failed=" + type(error).__name__, flush=True)
    finally:
        runner.mode("none")
        runner.restore()
        runner.save()
        runner.client.close()
    return 0 if runner.report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
