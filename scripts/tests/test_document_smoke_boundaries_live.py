"""Actual committed Docker containers are drained after lost acknowledgements."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "document_smoke_live", Path(__file__).parents[1] / "smoke_document_runtime.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
pytestmark = pytest.mark.skipif(
    os.environ.get("GPTHUB_DOCUMENT_SMOKE_BOUNDARIES_LIVE") != "1",
    reason="owned local Docker acknowledgement acceptance is opt-in",
)


@pytest.mark.parametrize(
    "case", ["create_lost_ack", "start_failure", "remove_lost_ack"]
)
def test_exact_owned_container_is_removed_after_failure(case, monkeypatch):
    original = smoke._run
    name = None
    inspection_count = 0
    monkeypatch.setattr(
        smoke, "_source_archive", lambda *_, **__: (b"synthetic", {"engine": "xelatex"})
    )

    def invoke(*args, **kwargs):
        nonlocal name, inspection_count
        if "create" in args:
            name = args[args.index("--name") + 1]
            result = original(*args, **kwargs)
            assert result.returncode == 0, "local_container_create_unavailable"
            if case == "create_lost_ack":
                raise RuntimeError("process_timeout")
            return result
        if "inspect" in args:
            inspection_count += 1
        if "start" in args:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
        result = original(*args, **kwargs)
        if "rm" in args and case == "remove_lost_ack":
            assert result.returncode == 0, "owned_container_remove_unavailable"
            raise RuntimeError("process_timeout")
        return result

    monkeypatch.setattr(smoke, "_run", invoke)
    try:
        with pytest.raises(RuntimeError) as raised:
            smoke._smoke_profile(
                "gpthub-document-runtime:latest", "generic_document", publication=False
            )
        assert str(raised.value) in {"process_timeout", "container_start"}
        assert name is not None and inspection_count >= 1
        remaining = original(
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^/{name}$",
            "--format",
            "{{.ID}}",
            timeout=15,
        )
        assert remaining.returncode == 0 and not remaining.stdout.strip(), (
            "owned_container_retained"
        )
    finally:
        # Retry only the exact labeled random-name cleanup if the assertion failed.
        if name is not None:
            monkeypatch.setattr(smoke, "_run", original)
            smoke._cleanup_container(name)
