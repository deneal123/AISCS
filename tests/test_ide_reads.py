import json
import os
import shlex
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.ide_reads import IdeReadFailure, IdeReadService
from infrastructure import ide_read_runtime as runtime


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/root",
        "../secret",
        "a/../b",
        "a//b",
        "a/",
        "a\\b",
        ".git/config",
        ".gpthub-state",
        "x/\x00",
        "x/\n",
        "x" * 1025,
    ],
)
async def test_forbidden_path_never_executes(path):
    run = AsyncMock()
    with pytest.raises(IdeReadFailure, match="ide_path_forbidden"):
        await IdeReadService(run).read(SimpleNamespace(), operation="file", path=path)
    run.assert_not_awaited()


async def test_repo_input_is_only_stdin_and_python_ignores_repo_imports():
    path = "a'; echo PRIVATE; '#.py"
    run = AsyncMock(
        return_value=SimpleNamespace(
            exit_code=0, truncated=False, stdout='{"entries": [], "truncated": false}'
        )
    )
    item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"))
    await IdeReadService(run).read(item, operation="tree", path=path)
    args, kwargs = run.await_args
    assert args[0] is item and shlex.split(args[1])[:3] == ["python3", "-I", "-c"]
    assert path not in args[1] and "/workspace" not in args[1]
    assert json.loads(kwargs["stdin_payload"]) == {
        "root": "/workspace",
        "path": path,
        "operation": "tree",
    }


@pytest.mark.parametrize(
    "body",
    [
        "[]",
        "null",
        "broken",
        '{"error": []}',
        '{"error": {"private": "value"}}',
        '{"error": "PRIVATE"}',
    ],
)
async def test_malformed_or_unknown_error_is_closed(body):
    run = AsyncMock(return_value=SimpleNamespace(exit_code=0, truncated=False, stdout=body))
    with pytest.raises(IdeReadFailure, match="ide_read_unavailable"):
        await IdeReadService(run).read(
            SimpleNamespace(policy=SimpleNamespace(root="/workspace")), operation="tree", path=""
        )


@pytest.mark.parametrize("changes", [{"exit_code": 1}, {"truncated": True}, {"timed_out": True}])
async def test_incomplete_subprocess_never_publishes_partial_json(changes):
    result = {"exit_code": 0, "truncated": False, "stdout": '{"entries": []}', **changes}
    with pytest.raises(IdeReadFailure):
        await IdeReadService(AsyncMock(return_value=SimpleNamespace(**result))).read(
            SimpleNamespace(policy=SimpleNamespace(root="/workspace")), operation="tree", path=""
        )


@pytest.mark.skipif(os.name != "posix", reason="descriptor-relative POSIX sandbox contract")
def test_descriptor_reader_excludes_links_and_special_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("PRIVATE", encoding="utf-8")
    (root / ".gpthub-state").write_text("PRIVATE", encoding="utf-8")
    (root / "binary").write_bytes(b"\x00\xff")
    (root / "link").symlink_to(tmp_path, target_is_directory=True)
    (root / "src" / "filelink").symlink_to(root / ".git" / "config")
    os.mkfifo(root / "fifo")

    def read(path, operation="file"):
        return runtime.execute({"root": str(root), "path": path, "operation": operation})

    tree = read("", "tree")
    assert {entry["path"] for entry in tree["entries"]} == {"src", "src/main.py", "binary"}
    assert not tree["truncated"]
    assert read("src/main.py")["content"] == "print('hello')\n"
    assert read("binary")["kind"] == "binary"
    for path in ("link/repo/src/main.py", "src/filelink", ".git/config", "../other"):
        assert read(path)["error"] == "ide_path_forbidden"
    assert read("fifo")["error"] == "ide_file_unsupported"
    assert read("absent")["error"] == "ide_file_missing"


@pytest.mark.skipif(os.name != "posix", reason="descriptor-relative POSIX sandbox contract")
def test_utf8_prefix_never_claims_a_complete_edit_digest(tmp_path):
    content = "a" * (runtime.MAX_BYTES - 1) + "я" + "tail"
    (tmp_path / "large").write_text(content, encoding="utf-8")
    result = runtime.execute({"root": str(tmp_path), "path": "large", "operation": "file"})
    assert result["kind"] == "text" and result["truncated"] and result["digest"] is None
    assert result["content"] == "a" * (runtime.MAX_BYTES - 1)


@pytest.mark.skipif(os.name != "posix", reason="descriptor-relative POSIX sandbox contract")
def test_tree_depth_and_entry_limits_are_visible_not_empty(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "nested").mkdir()
    (tmp_path / "src" / "nested" / "main.py").touch()
    monkeypatch.setattr(runtime, "MAX_DEPTH", 1)
    result = runtime.execute({"root": str(tmp_path), "operation": "tree"})
    assert result == {
        "entries": [{"path": "src", "type": "dir", "size": 0, "incomplete": True}],
        "truncated": True,
    }
    monkeypatch.setattr(runtime, "MAX_DEPTH", 6)
    monkeypatch.setattr(runtime, "MAX_ENTRIES", 2)
    result = runtime.execute({"root": str(tmp_path), "operation": "tree"})
    assert len(result["entries"]) == 2 and result["truncated"]
    assert all(entry["incomplete"] for entry in result["entries"])
