#!/usr/bin/env python3
"""Compare source Document Forge digests with immutable boot health identities."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AGENTS_RUNTIME = (
    ROOT / "agents" / "service" / "domain" / "documents" / "runtime_digest.py"
)
WORKSPACE_RUNTIME = (
    ROOT / "workspace" / "service" / "domain" / "documents" / "runtime_digest.py"
)
COMPILER_FILES = {
    "runner.py": ROOT / "workspace/docker/document_runner.py",
    "document_source_audit.py": ROOT / "workspace/docker/document_source_audit.py",
    "document_page_audit.py": ROOT / "workspace/docker/document_page_audit.py",
    "font_audit.py": ROOT / "workspace/service/domain/documents/font_audit.py",
    "source_identity.py": ROOT / "workspace/service/domain/documents/source_identity.py",
}


def _compiler_source_digest() -> str:
    digest = hashlib.sha256()
    for name, path in COMPILER_FILES.items():
        digest.update(f"{name}\0".encode())
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _live_compiler_digest() -> str:
    """Probe only the configured local image, with no mounts or provider calls."""

    compose = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / "docker/.env.dev"),
        "-f",
        str(ROOT / "docker/docker-compose.dev.yaml"),
        "--profile",
        "dev",
        "--profile",
        "celery",
    ]
    try:
        configured = subprocess.run(
            [
                *compose,
                "exec",
                "-T",
                "workspace",
                "python3",
                "-c",
                "from infrastructure.document_compiler import DOCUMENT_IMAGE; print(DOCUMENT_IMAGE)",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("compiler_runtime_unavailable") from None
    image = configured.stdout.strip()
    if configured.returncode or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}", image
    ):
        raise RuntimeError("compiler_runtime_unavailable")
    probe = (
        "import hashlib,pathlib; h=hashlib.sha256(); "
        f"names={list(COMPILER_FILES)!r}; "
        "[(h.update((n+'\\0').encode()), "
        "h.update((pathlib.Path('/opt/document-runtime')/n).read_bytes()), "
        "h.update(b'\\0')) for n in names]; print(h.hexdigest())"
    )
    name = "gpthub-compiler-freshness-" + secrets.token_hex(6)
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--name",
                name,
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user=65534:65534",
                "--memory=128m",
                "--pids-limit=32",
                "--cpus=1",
                "--entrypoint",
                "python3",
                image,
                "-B",
                "-c",
                probe,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        digest = result.stdout.strip()
        if result.returncode or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise RuntimeError("compiler_runtime_unavailable")
        return digest
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("compiler_runtime_unavailable") from None
    finally:
        try:
            subprocess.run(
                ["docker", "rm", "-f", name],
                cwd=ROOT,
                capture_output=True,
                timeout=15,
                check=False,
            )
            absent = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    f"name=^/{name}$",
                    "--format",
                    "{{.Names}}",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if absent.returncode or absent.stdout.strip():
                raise RuntimeError("compiler_cleanup_unavailable")
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError("compiler_cleanup_unavailable") from None


def _literal_assignment(path: Path, name: str) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"missing {name}")


def _source_identity(path: Path, *, base: Path) -> tuple[str, str]:
    version = str(_literal_assignment(path, "DOCUMENT_RUNTIME_VERSION"))
    files = set(str(item) for item in _literal_assignment(path, "_RUNTIME_FILES"))
    data_patterns = (
        _literal_assignment(path, "_RUNTIME_DATA_GLOBS")
        if path == WORKSPACE_RUNTIME
        else ()
    )
    for pattern in data_patterns:
        files.update(
            item.relative_to(base).as_posix()
            for item in base.glob(pattern)
            if item.is_file()
        )
    digest = hashlib.sha256()
    digest.update(f"{version}\n".encode())
    for relative in (
        sorted(files) if data_patterns else _literal_assignment(path, "_RUNTIME_FILES")
    ):
        source = base / relative
        digest.update(f"{relative}\0".encode())
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return version, digest.hexdigest()


def _live_health() -> dict[str, Any]:
    probe = (
        "import json,urllib.request;"
        "a=json.load(urllib.request.urlopen('http://agents:8090/health',timeout=15));"
        "w=json.load(urllib.request.urlopen('http://workspace:8080/health',timeout=15));"
        "print(json.dumps({'agents':a.get('document_runtime',{}),"
        "'workspace':w.get('documents',{})},separators=(',',':')))"
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ROOT / "docker" / ".env.dev"),
            "-f",
            str(ROOT / "docker" / "docker-compose.dev.yaml"),
            "--profile",
            "dev",
            "--profile",
            "celery",
            "exec",
            "-T",
            "backend",
            "python",
            "-c",
            probe,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("compose_health_unavailable")
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, TypeError, ValueError) as exc:
        raise RuntimeError("compose_health_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("compose_health_invalid")
    return payload


def _assert_live(
    live: dict[str, Any],
    *,
    agents: tuple[str, str],
    workspace: tuple[str, str],
) -> None:
    for name, expected in (("agents", agents), ("workspace", workspace)):
        actual = live.get(name)
        if not isinstance(actual, dict):
            raise RuntimeError(f"{name}_runtime_missing")
        version = str(actual.get("version") or actual.get("runtime_version") or "")
        digest = str(actual.get("digest") or actual.get("runtime_digest") or "")
        if (version, digest) != expected:
            raise RuntimeError(f"{name}_runtime_stale")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        agents = _source_identity(AGENTS_RUNTIME, base=AGENTS_RUNTIME.parent)
        workspace = _source_identity(
            WORKSPACE_RUNTIME, base=ROOT / "workspace" / "service"
        )
        compiler = _compiler_source_digest()
        if args.live:
            _assert_live(_live_health(), agents=agents, workspace=workspace)
            if _live_compiler_digest() != compiler:
                raise RuntimeError("compiler_runtime_stale")
    except (OSError, SyntaxError, TypeError, ValueError, RuntimeError) as exc:
        print(f"document runtime freshness failed: {exc}", file=sys.stderr)
        return 1
    mode = "live" if args.live else "source"
    print(
        "document runtime freshness: "
        f"mode={mode} agents={agents[0]}:{agents[1][:12]} "
        f"workspace={workspace[0]}:{workspace[1][:12]} compiler={compiler[:12]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
