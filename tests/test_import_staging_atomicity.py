"""A staged import batch is one publication unit, including failed/cancelled staging."""

import asyncio
from types import SimpleNamespace

import pytest
from application.importer import ImportRefused
from application.imports import ImportService


def fixture_service(*, failure=None, failed_index=1, sizes=None):
    item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"), imported=set())
    commands, snapshots = [], []
    fetch_count, stage_count = 0, 0

    async def fetcher(_url):
        nonlocal fetch_count
        fetch_count += 1
        if failure == "fetch" and fetch_count == failed_index:
            raise ImportRefused("source is temporarily unavailable")
        if sizes is not None:
            return b"x" * sizes[fetch_count - 1]
        return b"payload"

    async def run(_item, command, **_kwargs):
        nonlocal stage_count
        commands.append(command)
        if "mktemp" in command:
            stage_count += 1
            if stage_count == failed_index:
                if failure == "cancel":
                    raise asyncio.CancelledError
                if failure == "stage":
                    return SimpleNamespace(stdout="", exit_code=1)
            return SimpleNamespace(stdout="__OK__", exit_code=0)
        if "os.replace" in command:
            return SimpleNamespace(stdout="__IMPORTED__\tone.txt\n__KEPT__\ttwo.txt")
        return SimpleNamespace(stdout="", exit_code=0)

    async def snapshot(_item, kind):
        snapshots.append(kind)
        return {}

    async def revision(_item):
        return "base"

    return ImportService(run, snapshot, revision, fetcher), item, commands, snapshots


ENTRIES = [
    {"name": "one.txt", "url": "https://safe.example/one"},
    {"name": "two.txt", "url": "https://safe.example/two"},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["fetch", "stage"])
@pytest.mark.parametrize("failed_index", [1, 2])
async def test_one_failed_source_prevents_publication_of_other_staged_files(failure, failed_index):
    service, item, commands, snapshots = fixture_service(failure=failure, failed_index=failed_index)
    result = await service.execute(item, ENTRIES, expected_revision="base")

    assert not any("os.replace" in command for command in commands)
    assert result["imported"] == result["kept"] == 0
    assert all(entry["outcome"] == "stage_failed" for entry in result["files"])
    assert item.imported == set()
    assert snapshots == []
    assert sum(command.startswith("rm -rf ") for command in commands) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("sizes", [(6, 4), (6, 5), (11,)])
async def test_total_byte_budget_is_checked_before_staging_next_payload(monkeypatch, sizes):
    monkeypatch.setattr("application.imports.MAX_TOTAL_BYTES", 10)
    service, item, commands, snapshots = fixture_service(sizes=sizes)
    result = await service.execute(item, ENTRIES[: len(sizes)], expected_revision="base")
    stages = sum("mktemp" in command for command in commands)
    if sum(sizes) == 10:
        assert stages == 2
        assert result["imported"] == result["kept"] == 1
        assert snapshots == ["import"]
    else:
        assert stages == (1 if sizes[0] < 10 else 0)
        assert not any("os.replace" in command for command in commands)
        assert result["imported"] == result["kept"] == 0
        assert all(entry["outcome"] == "stage_failed" for entry in result["files"])
        assert result["files"][-1]["reason"] == "import byte limit reached"
        assert item.imported == set()
        assert snapshots == []
    assert sum(command.startswith("rm -rf ") for command in commands) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stage", "cancel"])
async def test_first_stage_failure_cleans_its_private_attempt_directory(failure):
    service, item, commands, snapshots = fixture_service(failure=failure)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await service.execute(item, ENTRIES[:1], expected_revision="base")
    else:
        result = await service.execute(item, ENTRIES[:1], expected_revision="base")
        assert result["files"][0]["outcome"] == "stage_failed"

    assert sum(command.startswith("rm -rf ") for command in commands) == 1
    assert not any("os.replace" in command for command in commands)
    assert snapshots == []


@pytest.mark.asyncio
async def test_complete_batch_preserves_collision_and_one_snapshot_contract():
    service, item, commands, snapshots = fixture_service()
    result = await service.execute(item, ENTRIES, expected_revision="base")

    assert result["imported"] == result["kept"] == 1
    assert [entry["outcome"] for entry in result["files"]] == ["imported", "kept"]
    assert item.imported == {"one.txt", "two.txt"}
    assert snapshots == ["import"]
    assert sum("os.replace" in command for command in commands) == 1
    assert sum(command.startswith("rm -rf ") for command in commands) == 1
