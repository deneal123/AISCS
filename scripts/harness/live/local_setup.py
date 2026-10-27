"""Секрет передаётся только через stdin собственному тестовому agents-процессу."""

import json
import runpy


def initialize_local_process(process, root):
    entries = runpy.run_path(str(root / "docker/sync_env.py"))["entries"]
    key = entries((root / "docker/.env.dev").read_text(encoding="utf-8")).get(
        "LOCAL_LLM_API_KEY", ""
    )
    if len(key) < 32:
        raise RuntimeError("local_llm_key_unavailable")
    process.stdin.write(json.dumps({"key": key}).encode() + b"\n")
    process.stdin.flush()
