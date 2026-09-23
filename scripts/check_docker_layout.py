#!/usr/bin/env python3
"""Verify the two-file Docker and dotenv contract without exposing secrets."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOCKER = ROOT / "docker"
COMPOSES = {
    "docker-compose.dev.yaml": ".env.dev",
    "docker-compose.yaml": ".env.prod",
}
ENV_FILES = (".env.example", ".env.dev", ".env.prod")
KEY_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)=(.*)$", re.MULTILINE)
INTERPOLATION_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
RETIRED_KEY_RE = re.compile(
    r"^(?:AGENTS__|MEMOS_|NEO4J_|QDRANT_|VIDEO_|WORKSPACE_)"
)
RETIRED_KEYS: set[str] = set()
GATES = {
    "AI_ASSISTANT__AUDIENCE_ENABLED": "{}",
    "AI_ASSISTANT__ENABLED": "true",
    "AI_ASSISTANT__PROVIDER_ENABLED": "{}",
    "AI_ASSISTANT__TOOL_ENABLED": "{}",
    "ALTER_GRAPH__CONSENT_POLICY_VERSION": "v1",
    "ALTER_GRAPH__CONSENT_REQUIRED": "true",
    "ALTER_GRAPH__CONSENT_SCOPE": "alter_identity_explicit_signals",
    "ALTER_GRAPH__ENABLED": "true",
    "ALTER_RANKING__ENABLED": "true",
    "VOICE_TRANSCRIPTION__ENABLED": "true",
    "FILE__SETTINGS__LIVENESS_SUBMISSION_ENABLED": "false",
    "PAYMENTS__RECEIPT_ENABLED": "false",
    "PAYMENTS__SALES_ENABLED": "false",
    "RANKING__BIOMETRIC_PROCESSING_ENABLED": "false",
    "RANKING__ALLOW_NEUTRAL_RANKING": "true",
    "RANKING__ENABLED": "true",
    "RANKING__MEDIA_PROCESSING_ENABLED": "false",
    "SERVICE__PRODUCT_MODE": "dating",
    "STORAGE__BACKEND": "minio",
}
DEV_MAILPIT_MARKERS = (
    "mailpit:",
    "axllent/mailpit:v1.30.7",
    "MAIL__HOST: mailpit",
    '"127.0.0.1:8025:8025"',
)
DEV_MEDIA_MARKERS = (
    "STORAGE__BACKEND: minio",
    "MINIO__ENDPOINT: minio:9000",
    "MINIO__PUBLIC_ENDPOINT: http://127.0.0.1:${MINIO_PORT:-9020}",
)
DEV_LOOPBACK_PORT_MARKERS = (
    '"127.0.0.1:${FRONTEND_PORT:-3000}:3000"',
    '"127.0.0.1:${BACKEND_PORT:-8000}:8000"',
    '"127.0.0.1:${PG_PUBLISH_PORT:-5442}:5432"',
    '"127.0.0.1:${MINIO_PORT:-9020}:9000"',
    '"127.0.0.1:${MINIO_CONSOLE_PORT:-9021}:9001"',
)
PROD_SYNTHETIC_MAILPIT_MARKERS = (
    'profiles: ["synthetic-mail"]',
    "axllent/mailpit:v1.30.7",
    '"127.0.0.1:8025:8025"',
)
# The dev Compose file forces MinIO for its core services.  Production storage
# selection belongs to deployment-only `preflight_dating.py`, which reads the
# deployer-owned ignored dotenv immediately before an external release.  Do not
# rewrite that file merely to make a source-layout check pass.
DEPLOYMENT_PREFLIGHT_GATES = {"STORAGE__BACKEND"}
# These keys were added to make the Mailpit boundary explicit. Existing ignored
# local/prod dotenv files may omit them while they retain backend defaults; an
# external synthetic staging run still requires their exact values through
# `preflight_dating.py` before Compose starts. Do not use this exemption for
# credentials or feature gates.
TRANSITIONAL_OPTIONAL_ENV_KEYS = {
    "MAIL__START_TLS",
    "MAIL__ALLOW_UNAUTHENTICATED",
    "RANKING__MAX_BODY_BYTES",
}


def parse_dotenv(path: Path) -> dict[str, str]:
    return {match.group(1): match.group(2).strip() for match in KEY_RE.finditer(path.read_text(encoding="utf-8"))}


def is_retired(key: str) -> bool:
    return key in RETIRED_KEYS or bool(RETIRED_KEY_RE.match(key))


def main() -> int:
    errors: list[str] = []
    actual_compose = {path.name for path in DOCKER.glob("docker-compose*.yaml")}
    expected_compose = set(COMPOSES)
    if actual_compose != expected_compose:
        missing = sorted(expected_compose - actual_compose)
        extra = sorted(actual_compose - expected_compose)
        if missing:
            errors.append(f"missing Compose files: {', '.join(missing)}")
        if extra:
            errors.append(f"unsupported Compose files: {', '.join(extra)}")

    template_path = DOCKER / ".env.example"
    if not template_path.is_file():
        errors.append("docker/.env.example is missing")
        template: dict[str, str] = {}
    else:
        template = parse_dotenv(template_path)
        legacy = sorted(key for key in template if is_retired(key))
        if legacy:
            errors.append(f"retired keys remain in .env.example: {', '.join(legacy)}")
        for key, expected in GATES.items():
            if template.get(key) != expected:
                errors.append(f".env.example gate is not fail-closed: {key}")

    for name, env_name in COMPOSES.items():
        path = DOCKER / name
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        active_body = "\n".join(
            line for line in body.splitlines() if not line.lstrip().startswith("#")
        )
        if f"- ./{env_name}" not in body:
            errors.append(f"{name} must use {env_name}")
        if re.search(r'profiles:\s*\[[^\]]*\b(?:dev|prod|celery)\b', active_body):
            errors.append(f"{name} must not hide core services behind dev/prod/celery profiles")
        if "  whisper:\n" not in body:
            errors.append(f"{name} must define the core Whisper sidecar")
        if "VOICE_TRANSCRIPTION__ENABLED" not in body:
            errors.append(f"{name} must configure explicit Alter voice transcription")
        if name == "docker-compose.dev.yaml":
            for marker in DEV_MAILPIT_MARKERS:
                if marker not in body:
                    errors.append(f"{name} must keep isolated dev Mailpit ({marker})")
            for marker in DEV_MEDIA_MARKERS:
                if marker not in body:
                    errors.append(f"{name} must keep MinIO as the dating media path ({marker})")
            for marker in DEV_LOOPBACK_PORT_MARKERS:
                if marker not in body:
                    errors.append(f"{name} must publish local development ports on loopback ({marker})")
        if name == "docker-compose.yaml":
            for marker in PROD_SYNTHETIC_MAILPIT_MARKERS:
                if marker not in body:
                    errors.append(
                        f"{name} must keep staging Mailpit explicit and loopback-only ({marker})"
                    )
        for key in INTERPOLATION_RE.findall(active_body):
            if key not in template:
                errors.append(f"{name} interpolates undeclared key: {key}")
        for marker in ("${APP_DOMAIN", "${NGINX_PORT"):
            if marker in body:
                errors.append(f"{name} contains retired duplicate alias: {marker[2:]}")

    for env_name in ENV_FILES[1:]:
        path = DOCKER / env_name
        if not path.is_file():
            continue
        values = parse_dotenv(path)
        missing = sorted(
            (set(template) - set(values)) - TRANSITIONAL_OPTIONAL_ENV_KEYS
        )
        extra = sorted(set(values) - set(template))
        if missing:
            errors.append(f"{env_name} misses template keys: {', '.join(missing)}")
        if extra:
            errors.append(f"{env_name} has undeclared keys: {', '.join(extra)}")
        legacy = sorted(key for key in values if is_retired(key))
        if legacy:
            errors.append(f"{env_name} retains retired keys: {', '.join(legacy)}")
        for key, expected in GATES.items():
            if key in DEPLOYMENT_PREFLIGHT_GATES:
                continue
            if values.get(key) != expected:
                errors.append(f"{env_name} gate is not fail-closed: {key}")

    if errors:
        print("Docker contract check failed (key names only):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    checked = [name for name in ENV_FILES if (DOCKER / name).is_file()]
    print(
        "Docker contract is consistent: two Compose files; checked dotenv schemas "
        f"({', '.join(checked)}); no values emitted."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
