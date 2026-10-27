"""Single-executor process isolation, repeat delivery, durable receipts and explicit cleanup ack."""

from __future__ import annotations

import json
import multiprocessing as mp
import shutil
import threading
from pathlib import Path
from time import time

from service.contracts import ExecutionRequest, SimulationConfig
from service.shared.json_io import write_json


def run_child(payload: dict, directory: str) -> None:
    from service.main import build_generation

    target = Path(directory)
    try:
        config = SimulationConfig.model_validate(payload)
        build_generation().execute(config, target)
    except Exception as exc:
        target.mkdir(parents=True, exist_ok=True)
        write_json(target / "error.json", {"type": type(exc).__name__, "message": str(exc)[:1000]})
        raise


class Executions:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.processes: dict[str, mp.Process] = {}

    def receipt(self, execution_id: str) -> Path:
        return self.root / execution_id / "receipt.json"

    def save(self, record: dict) -> None:
        path = self.receipt(record["execution_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        write_json(temporary, record)
        temporary.replace(path)

    def status(self, execution_id: str) -> dict:
        with self.lock:
            path = self.receipt(execution_id)
            if not path.is_file():
                raise KeyError(execution_id)
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["status"] == "running":
                process = self.processes.get(execution_id)
                if process is None or not process.is_alive():
                    if process:
                        process.join(timeout=1)
                    output = path.parent / "output"
                    manifest = output / "manifest.json"
                    if manifest.exists() and process is not None and process.exitcode == 0:
                        record.update(status="completed", manifest=json.loads(manifest.read_text()))
                    elif process is None:
                        record.update(status="interrupted", error="Executor restarted")
                    else:
                        error = output / "error.json"
                        record.update(
                            status="failed",
                            error=(
                                json.loads(error.read_text())
                                if error.exists()
                                else {"message": f"Solver exit {process.exitcode}"}
                            ),
                        )
                    record["finished_at"] = time()
                    self.save(record)
            return record

    def start(self, request: ExecutionRequest) -> dict:
        with self.lock:
            if self.receipt(request.execution_id).exists():
                previous = self.status(request.execution_id)
                if previous["configuration_sha256"] != request.config.digest():
                    raise ValueError("Execution ID already belongs to another configuration")
                return previous
            for execution_id in list(self.processes):
                if self.status(execution_id)["status"] == "running":
                    raise RuntimeError("Executor busy")
            output = self.root / request.execution_id / "output"
            record = {
                "execution_id": request.execution_id,
                "status": "running",
                "configuration_sha256": request.config.digest(),
                "started_at": time(),
                "acknowledged": False,
            }
            process = mp.get_context("spawn").Process(
                target=run_child,
                args=(request.config.model_dump(), str(output)),
                daemon=True,
            )
            self.save(record)
            try:
                process.start()
            except Exception:
                record.update(status="failed", error="Could not start solver")
                self.save(record)
                raise
            self.processes[request.execution_id] = process
            return record

    def cancel(self, execution_id: str) -> dict:
        with self.lock:
            record = self.status(execution_id)
            if record["status"] == "running":
                process = self.processes.get(execution_id)
                if process and process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=5)
                record.update(status="cancelled", finished_at=time())
                self.save(record)
            return record

    def acknowledge(self, execution_id: str, configuration_sha256: str) -> dict:
        with self.lock:
            record = self.status(execution_id)
            if (
                record["status"] != "completed"
                or record["configuration_sha256"] != configuration_sha256
            ):
                raise ValueError("Only the verified completed configuration can be acknowledged")
            # root and execution id are service-owned; never accept caller filesystem paths.
            output = self.receipt(execution_id).parent / "output"
            if output.exists():
                shutil.rmtree(output)
            record["acknowledged"] = True
            self.save(record)
            return record

    def discard(self, execution_id: str, configuration_sha256: str) -> dict:
        with self.lock:
            record = self.status(execution_id)
            if record["configuration_sha256"] != configuration_sha256 or record["acknowledged"]:
                raise ValueError("Cannot discard another or already published configuration")
            self.cancel(execution_id)
            output = self.receipt(execution_id).parent / "output"
            if output.exists():
                shutil.rmtree(output)
            record.update(status="cancelled", discarded=True, finished_at=time())
            self.save(record)
            return record

    def close(self) -> None:
        for execution_id in list(self.processes):
            with self.lock:
                previous = self.status(execution_id)
                if previous["status"] == "running":
                    record = self.cancel(execution_id)
                    record.update(status="interrupted", error="Executor shutdown")
                    self.save(record)
