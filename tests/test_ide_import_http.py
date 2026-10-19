import base64
import hashlib

import pytest
from test_ide_agent_write_http import fixture


def request(content=b"\0\xffPK\x03\x04"):
    return dict(
        user_id="owner",
        token="private",
        path="data.zip",
        operation="import",
        content=base64.b64encode(content).decode(),
        sha256=hashlib.sha256(content).hexdigest(),
        coordination_capability="capability",
        coordination_fence=7,
    )


def test_private_import_uses_the_same_lock_lease_and_exact_binary_writer():
    client, guard, writer = fixture()
    response = client.post("/workspaces/owned/ide/import", json=request())
    assert response.status_code == 200
    assert guard.await_args.kwargs == dict(path="data.zip", workspace_id="owned")
    assert guard.await_args.args[0].coordination_fence == 7
    assert writer.await_args.kwargs == dict(
        path="data.zip", operation="import", content=b"\0\xffPK\x03\x04", expected_digest=None
    )


@pytest.mark.parametrize(
    "change",
    [
        dict(content="not base64"),
        dict(sha256="a" * 64),
        dict(expected_digest="b" * 64),
        dict(coordination_fence=0),
        dict(url="https://example.test/private"),
    ],
)
def test_invalid_private_import_never_reaches_the_writer(change):
    client, _, writer = fixture()
    assert (
        client.post("/workspaces/owned/ide/import", json={**request(), **change}).status_code == 422
    )
    writer.assert_not_awaited()


def test_other_write_endpoints_do_not_gain_binary_import_access():
    client, _, writer = fixture()
    for suffix in ["write", "agent/write"]:
        assert client.post(f"/workspaces/owned/ide/{suffix}", json=request()).status_code == 422
    writer.assert_not_awaited()
