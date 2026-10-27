import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.application.admission.ide import apply_ide_context
from service.domain.base import _document_tools
from service.domain.execution.context import (
    PrivateRunResources,
    tool_context_payload,
    use_run_execution,
)
from service.domain.runners.tool_runtime import ToolCallOutcome
from service.domain.tools.ide import tools as tools
from service.domain.tools.workspace import client as workspace_client

REF = dict(
    workspace_id="private",
    token="SECRET",
    user_id="owner",
    coordination_capability="PRIVATE",
    ide_context=dict(repository_id=str(uuid4()), generation="a" * 64),
)


def contents(path="main.py", content="before"):
    return dict(
        path=path,
        kind="text",
        size=len(content.encode()),
        content=content,
        digest=hashlib.sha256(content.encode()).hexdigest(),
        truncated=False,
    )


@pytest.fixture
def requests(monkeypatch):
    seen = []
    state = {"main.py": "before"}

    async def call(ref, endpoint, payload):
        assert ref["token"] == "SECRET" and ref.get("ide_context") == REF["ide_context"]
        assert not {"token", "user_id", "workspace_id", "coordination_fence"} & payload.keys()
        seen.append((endpoint, payload))
        if endpoint == "ide/file":
            return contents(payload["path"], state[payload["path"]])
        if endpoint == "ide/agent/write":
            state[payload["path"]] = payload["content"]
            return dict(
                written=True,
                path=payload["path"],
                kind="file",
                size=len(payload["content"].encode()),
                digest=hashlib.sha256(payload["content"].encode()).hexdigest(),
            )
        return dict(entries=[], truncated=False)

    monkeypatch.setattr(tools, "call", call)
    return seen, state


@pytest.mark.asyncio
async def test_read_then_write_uses_the_observed_digest_and_updates_only_on_ack(requests):
    seen, state = requests
    with use_run_execution(PrivateRunResources.from_request(workspace_ref=REF)) as execution:
        read = await tools.ide_read(None, '{"path":"main.py"}')
        assert read.succeeded
        result = json.loads(read.text)
        assert "SECRET" not in json.dumps(result)
        answer = await tools.ide_write(
            None, json.dumps(dict(path="main.py", content="after", base_digest=result["digest"]))
        )
        assert answer.succeeded and json.loads(answer.text)["written"]
        assert seen[-1][1]["expected_digest"] == result["digest"]
        assert execution.workspace.ide_writes == {"main.py": hashlib.sha256(b"after").hexdigest()}
        assert state["main.py"] == "after"
        assert "main.py" not in execution.workspace.ide_reads


@pytest.mark.asyncio
async def test_unread_file_cannot_be_overwritten_or_forge_a_base(requests):
    seen, _ = requests
    with use_run_execution(PrivateRunResources.from_request(workspace_ref=REF)) as execution:
        answer = await tools.ide_write(
            None, json.dumps(dict(path="main.py", content="after", base_digest="a" * 64))
        )
        assert isinstance(answer, ToolCallOutcome) and answer.billable is False
        assert not seen and not execution.workspace.ide_writes


@pytest.mark.asyncio
async def test_new_file_is_create_only_and_uses_no_git_or_exec(requests):
    seen, state = requests
    with use_run_execution(PrivateRunResources.from_request(workspace_ref=REF)):
        answer = await tools.ide_write(
            None, json.dumps(dict(path="new.py", content="print(1)", base_digest=None))
        )
        assert answer.succeeded and json.loads(answer.text)["written"]
        assert state["new.py"] == "print(1)"
        assert seen == [
            (
                "ide/agent/write",
                dict(path="new.py", operation="file", content="print(1)", expected_digest=None),
            )
        ]


@pytest.mark.asyncio
async def test_bounded_preview_cannot_full_replace_but_unique_edit_preserves_the_tail(requests):
    _, state = requests
    state["main.py"] = "target\n" + '\n"\\'.join(["tail"] * 12000)
    before = state["main.py"]
    with use_run_execution(PrivateRunResources.from_request(workspace_ref=REF)):
        raw = await tools.ide_read(None, '{"path":"main.py"}')
        assert raw.succeeded
        result = json.loads(raw.text)
        assert len(raw.text) < 24000 and result["truncated"] and not result["editable"]
        rejected = await tools.ide_write(
            None,
            json.dumps(dict(path="main.py", content="lost tail", base_digest=result["digest"])),
        )
        assert isinstance(rejected, ToolCallOutcome) and not rejected.billable
        answer = await tools.ide_edit(
            None,
            json.dumps(
                dict(path="main.py", old="target", new="changed", base_digest=result["digest"])
            ),
        )
        assert answer.succeeded and json.loads(answer.text)["written"]
        assert state["main.py"] == before.replace("target", "changed", 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["../outside", ".git/config", ".gpthub-state", "/root/file", "a\\b"]
)
async def test_unsafe_paths_are_not_dispatched_or_billed(requests, path):
    seen, _ = requests
    with use_run_execution(PrivateRunResources.from_request(workspace_ref=REF)):
        result = await tools.ide_write(
            None, json.dumps(dict(path=path, content="", base_digest=None))
        )
        assert isinstance(result, ToolCallOutcome) and result.billable is False
    assert not seen


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("exec", {"command": "true"}),
        ("files/write", {"path": "main.py"}),
        ("snapshot", {}),
        ("ide/agent/write", {"token": "EVIL"}),
    ],
)
async def test_private_ide_transport_cannot_fall_back_to_legacy_or_accept_model_credentials(
    endpoint, payload
):
    with pytest.raises(workspace_client.WorkspaceUnavailable):
        await workspace_client.call(REF, endpoint, payload)


def test_context_keeps_capability_private_and_does_not_grant_paid_tools():
    with use_run_execution(PrivateRunResources.from_request(workspace_ref=REF)) as execution:
        assert apply_ide_context(execution)
        assert execution.policy.flag("ide_tools_enabled")
        assert not execution.policy.flag("video_tool_enabled")
        tools_selected = _document_tools(
            [SimpleNamespace(name="ws_run"), SimpleNamespace(name="tex_compile")]
        )
        assert {tool.name for tool in tools_selected} == {tool.name for tool in tools.TOOLS}
        assert "workspace_ref" not in tool_context_payload({}, "open_webpage")
        assert tool_context_payload({}, "ide_read_file")["workspace_ref"]["token"] == "SECRET"
        assert "SECRET" not in repr(execution.workspace)


@pytest.mark.asyncio
async def test_bad_write_ack_is_unknown_not_a_confirmed_noop(monkeypatch):
    async def call(*args):
        return {"written": True, "path": "other.py"}

    monkeypatch.setattr(tools, "call", call)
    with use_run_execution(PrivateRunResources.from_request(workspace_ref=REF)) as execution:
        result = await tools.ide_write(
            None, json.dumps(dict(path="new.py", content="print(1)", base_digest=""))
        )
        assert isinstance(result, ToolCallOutcome)
        assert execution.workspace.ide_unconfirmed is True
        assert execution.workspace.ide_writes == {}


@pytest.mark.asyncio
async def test_private_read_uses_strict_read_dto_without_mutation_credentials(monkeypatch):
    import httpx

    seen = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, json, headers):
            seen.append((url, json))
            return httpx.Response(200, json={"entries": [], "truncated": False})

    monkeypatch.setattr(workspace_client, "_settings", lambda: ("http://workspace:8080", 10, True))
    monkeypatch.setattr(workspace_client.httpx, "AsyncClient", Client)
    await workspace_client.call(REF, "ide/tree", {"path": ""})
    assert len(seen) == 1
    assert set(seen[0][1]) == {"path", "user_id", "token"}
