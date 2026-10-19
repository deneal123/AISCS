"""Opt-in atomic staging/cleanup on a real isolated, offline runtime filesystem."""

import asyncio
import json
import os
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest
from application.importer import ImportRefused
from application.imports import ImportService

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.getenv("S37_LIVE_IMPORT_ATOMICITY") != "1", reason="native import shell"),
]


async def docker(*arguments, payload=None):
    result = await asyncio.to_thread(
        subprocess.run, ["docker", *arguments], input=payload, capture_output=True, timeout=30
    )
    assert result.returncode == 0, "import_fixture_docker_operation_failed"
    return result.stdout.decode().strip()


@pytest.mark.parametrize(
    "scenario", ["fetch_failure", "stage_failure", "cancel", "byte_limit", "published"]
)
async def test_native_batch_never_publishes_a_staged_subset_or_leaves_attempt_files(
    scenario, monkeypatch
):
    if scenario == "byte_limit":
        # Scaled test budget only; production's 64 MiB limit is unchanged.
        monkeypatch.setattr("application.imports.MAX_TOTAL_BYTES", 31)
    name = "s37-import-" + uuid4().hex
    try:
        await docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "gpthub.s37.import=1",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            "--memory=128m",
            "--cpus=1",
            "--pids-limit=32",
            "--tmpfs",
            "/workspace:rw,size=32m,mode=1777",
            "gpthub-workspace-runtime:latest",
            "sleep",
            "180",
        )
        await docker("exec", name, "sh", "-c", "printf 'user edit' > /workspace/two.txt")
        stage_count = 0
        snapshot_calls = []

        async def run(_item, command, *, stdin_payload=None):
            nonlocal stage_count
            output = await docker("exec", "-i", name, "sh", "-c", command, payload=stdin_payload)
            if "mktemp" in command:
                stage_count += 1
                if stage_count == 2:
                    # Fault boundary after a real staged write, before acknowledgement.
                    if scenario == "cancel":
                        raise asyncio.CancelledError
                    if scenario == "stage_failure":
                        output = ""
            return SimpleNamespace(stdout=output)

        async def snapshot(_item, kind):
            snapshot_calls.append(kind)
            return {"committed": True}

        async def revision(_item):
            return "base"

        async def fetcher(url):
            if scenario == "fetch_failure" and url.endswith("two"):
                raise ImportRefused("source is temporarily unavailable")
            return b"library original"

        item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"), imported=set())
        service = ImportService(run, snapshot, revision, fetcher)
        entries = [
            {"name": "one.txt", "url": "https://safe.example/one"},
            {"name": "two.txt", "url": "https://safe.example/two"},
        ]
        if scenario == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await service.execute(item, entries, expected_revision="base")
        else:
            result = await service.execute(item, entries, expected_revision="base")
            assert result["imported"] == (1 if scenario == "published" else 0)
            assert result["kept"] == (1 if scenario == "published" else 0)

        probe = (
            "import json,pathlib; r=pathlib.Path('/workspace'); "
            "print(json.dumps({'names':sorted(p.name for p in r.iterdir() if p.is_file()),"
            "'kept':(r/'two.txt').read_text()=='user edit',"
            "'staging_empty':not any((r/'.gpthub-import-staging').iterdir())}))"
        )
        state = json.loads(await docker("exec", name, "python3", "-c", probe))
        assert state["names"] == (
            ["one.txt", "two.txt"] if scenario == "published" else ["two.txt"]
        )
        assert state["kept"] and state["staging_empty"]
        assert snapshot_calls == (["import"] if scenario == "published" else [])
        assert item.imported == ({"one.txt", "two.txt"} if scenario == "published" else set())
        if scenario == "byte_limit":
            assert stage_count == 1
            assert result["files"][1]["reason"] == "import byte limit reached"
    finally:
        # Exact isolated fixture name only; no managed workspace or broad label cleanup.
        await docker("rm", "-f", name)


@pytest.mark.parametrize("alias", ["project", "figures", "destination", "staging", "none"])
async def test_nested_project_asset_never_follows_a_destination_or_staging_alias(alias):
    name = "s37-pdf-asset-" + uuid4().hex
    destination = "documents/paper/figures/library_fixture.png"
    payload = b"\x00\x01owned-library-binary-fixture"
    try:
        await docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "gpthub.s37.import=1",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            "--memory=128m",
            "--cpus=1",
            "--pids-limit=32",
            "--tmpfs",
            "/workspace:rw,size=32m,mode=1777",
            "gpthub-workspace-runtime:latest",
            "sleep",
            "180",
        )
        setup = """
import pathlib,sys
r=pathlib.Path('/workspace'); foreign=r/'foreign'; foreign.mkdir()
alias=sys.argv[1]
if alias == 'project':
    (r/'documents').symlink_to(foreign, target_is_directory=True)
else:
    project=r/'documents/paper'; project.mkdir(parents=True)
    if alias == 'figures':
        (project/'figures').symlink_to(foreign, target_is_directory=True)
    else:
        (project/'figures').mkdir()
        if alias == 'destination':
            (foreign/'sentinel').write_bytes(b'untouched')
            (project/'figures/library_fixture.png').symlink_to(foreign/'sentinel')
if alias == 'staging':
    (r/'.gpthub-import-staging').symlink_to(foreign, target_is_directory=True)
"""
        await docker("exec", name, "python3", "-c", setup, alias)
        snapshots = []

        async def run(_item, command, *, stdin_payload=None):
            process = await asyncio.to_thread(
                subprocess.run,
                ["docker", "exec", "-i", name, "sh", "-c", command],
                input=stdin_payload,
                capture_output=True,
                timeout=30,
            )
            return SimpleNamespace(stdout=process.stdout.decode(), exit_code=process.returncode)

        async def snapshot(_item, kind):
            snapshots.append(kind)
            return {}

        async def revision(_item):
            return "base"

        async def fetcher(_url):
            return payload

        item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"), imported=set())
        result = await ImportService(run, snapshot, revision, fetcher).execute(
            item,
            [{"name": destination, "url": "https://owned.invalid/fixture"}],
            expected_revision="base",
        )
        assert result["imported"] == (1 if alias == "none" else 0)
        assert result["kept"] == 0
        probe = """
import json,pathlib
r=pathlib.Path('/workspace'); foreign=r/'foreign'; staging=r/'.gpthub-import-staging'
print(json.dumps({'foreign':sorted(str(p.relative_to(foreign)) for p in foreign.rglob('*')),
 'sentinel': (foreign/'sentinel').read_text() if (foreign/'sentinel').exists() else None,
 'asset_hex':(r/'documents/paper/figures/library_fixture.png').read_bytes().hex()
   if not (r/'documents').is_symlink() and not (r/'documents/paper/figures').is_symlink()
   and (r/'documents/paper/figures/library_fixture.png').is_file() else None,
 'staging_empty':staging.is_symlink() or not staging.exists() or not any(staging.iterdir())}))
"""
        observed = json.loads(await docker("exec", name, "python3", "-c", probe))
        assert observed["foreign"] == (["sentinel"] if alias == "destination" else [])
        assert observed["sentinel"] == ("untouched" if alias == "destination" else None)
        if alias == "none":
            assert observed["asset_hex"] == payload.hex()
        assert observed["staging_empty"]
        assert snapshots == (["import"] if alias == "none" else [])
    finally:
        await docker("rm", "-f", name)
