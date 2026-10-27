"""Общий запуск изолированных PG-проб без публикации SQL, ключей и диагностики."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

from scripts.harness.live.host import docker, remove_source, temporary


def run_probe(module, paths):
    if re.fullmatch(r"[a-z_]+", module) is None:
        raise ValueError("probe_module_invalid")
    root = Path(__file__).resolve().parents[1]
    paths = ["scripts/harness/runtime.py", "scripts/harness/" + module + ".py", *paths]
    files = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}
    container = "gpthub-dev-backend-1"
    directory = temporary(container)
    try:
        docker("exec", container, "mkdir", "-p", directory + "/scripts/harness")
        for name in ("runtime.py", module + ".py"):
            docker(
                "cp",
                str(root / "scripts/harness" / name),
                container + ":" + directory + "/scripts/harness/" + name,
            )
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "python",
                "-c",
                "import runpy,sys;sys.path.insert(0,sys.argv[1]);"
                "runpy.run_module(sys.argv[2],run_name='__main__')",
                directory,
                "scripts.harness." + module,
            ],
            input=json.dumps({"files": files}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
    finally:
        remove_source(container, directory)
    try:
        outcome = json.loads(result.stdout)
    except ValueError:
        raise AssertionError("harness_pg_probe_output_invalid") from None
    assert result.returncode == 0, f"harness_pg_probe_failed:{outcome}"
    return outcome
