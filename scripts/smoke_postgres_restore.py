"""Isolated schema + synthetic-data restore acceptance, never a production restore.

Read only the dev schema. All data fixtures and dumps live in memory/tmpfs inside
an offline disposable PostgreSQL container; no original user rows are exported.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid

SOURCE = "gpthub-dev-postgres-1"
LABEL = "gpthub.acceptance=s37-postgres-restore"
MAX_DUMP = 16 * 1024 * 1024


def command(args: list[str], *, payload: bytes | None = None, timeout: int = 60) -> bytes:
    result = subprocess.run(args, input=payload, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("restore_command_failed")
    if len(result.stdout) > MAX_DUMP:
        raise RuntimeError("restore_dump_limit")
    return result.stdout


def sql(container: str, database: str, statement: bytes) -> bytes:
    return command(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-U",
            "postgres",
            "-d",
            database,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
        ],
        payload=statement,
    )


def cleanup(container: str) -> None:
    # Never delete a guessed name or a pre-existing deployment container.
    if not re.fullmatch(r"s37-pg-restore-[0-9a-f]{32}", container):
        raise RuntimeError("restore_cleanup_target")
    details = json.loads(command(["docker", "inspect", container]))[0]
    if details.get("Config", {}).get("Labels", {}).get("gpthub.acceptance") != LABEL.split("=")[1]:
        raise RuntimeError("restore_cleanup_owner")
    command(["docker", "rm", "-f", container])


def allocate(container: str, image: str, uid: str, gid: str) -> None:
    """Create the isolated runtime; caller owns cleanup even after a lost ACK."""
    command(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container,
            "--label",
            LABEL,
            "--network",
            "none",
            "--read-only",
            "--user",
            f"{uid}:{gid}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--pids-limit",
            "128",
            "--tmpfs",
            f"/var/lib/postgresql/data:rw,nosuid,noexec,size=256m,uid={uid},gid={gid}",
            "--tmpfs",
            f"/var/run/postgresql:rw,nosuid,noexec,uid={uid},gid={gid}",
            "--tmpfs",
            "/tmp:rw,nosuid,noexec,size=32m",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_DB=fixture_source",
            image,
        ]
    )


def run() -> dict[str, bool]:
    if os.getenv("S37_LIVE_POSTGRES_RESTORE") != "1":
        raise RuntimeError("restore_opt_in_required")
    image = command(["docker", "inspect", "--format", "{{.Image}}", SOURCE]).decode().strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise RuntimeError("restore_image_invalid")
    # Values expand only within the existing container, never into diagnostics.
    schema = command(
        [
            "docker",
            "exec",
            SOURCE,
            "sh",
            "-c",
            'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --schema-only --no-owner --no-acl',
        ]
    )
    uid = command(["docker", "exec", SOURCE, "id", "-u", "postgres"]).decode().strip()
    gid = command(["docker", "exec", SOURCE, "id", "-g", "postgres"]).decode().strip()
    if not uid.isdigit() or not gid.isdigit():
        raise RuntimeError("restore_user_invalid")
    container = "s37-pg-restore-" + uuid.uuid4().hex
    try:
        allocate(container, image, uid, gid)
        deadline = time.monotonic() + 45
        while True:
            ready = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-U", "postgres"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if ready.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("restore_start_timeout")
            time.sleep(0.5)
        sql(container, "fixture_source", schema)
        sql(
            container,
            "fixture_source",
            b"""
            CREATE SCHEMA restore_acceptance;
            CREATE TABLE restore_acceptance.fixture
                (id integer PRIMARY KEY, payload text NOT NULL, parent integer REFERENCES
                 restore_acceptance.fixture(id));
            INSERT INTO restore_acceptance.fixture VALUES
                (1,'synthetic-only',NULL),(2,'synthetic-child',1);
        """,
        )
        dump = command(
            [
                "docker",
                "exec",
                container,
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                "fixture_source",
                "-Fc",
                "--no-owner",
                "--no-acl",
            ]
        )
        command(
            [
                "docker",
                "exec",
                container,
                "createdb",
                "-U",
                "postgres",
                "fixture_restored",
            ]
        )
        command(
            [
                "docker",
                "exec",
                "-i",
                container,
                "pg_restore",
                "-U",
                "postgres",
                "-d",
                "fixture_restored",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
            ],
            payload=dump,
        )
        if (
            sql(
                container,
                "fixture_restored",
                b"""
            SELECT count(*)=2 AND bool_and(payload LIKE 'synthetic-%')
            FROM restore_acceptance.fixture;
            SELECT count(*)=1 FROM restore_acceptance.fixture c
            JOIN restore_acceptance.fixture p ON c.parent=p.id;
        """,
            ).strip()
            != b"t\nt"
        ):
            raise RuntimeError("restore_data_mismatch")
        inventory = b"""
            SELECT md5(string_agg(table_schema||'.'||table_name, ',' ORDER BY
            table_schema, table_name)) FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog','information_schema');
        """
        if sql(container, "fixture_source", inventory) != sql(
            container, "fixture_restored", inventory
        ):
            raise RuntimeError("restore_schema_mismatch")
        return {
            "schema_restored": True,
            "synthetic_data_restored": True,
            "offline": True,
        }
    finally:
        cleanup(container)


if __name__ == "__main__":
    try:
        print(json.dumps(run(), sort_keys=True))
    except Exception:
        # Never serialize process output, DB statements, credentials or dump bytes.
        print(json.dumps({"status": "failed", "code": "restore_acceptance_failed"}))
        raise SystemExit(1) from None
