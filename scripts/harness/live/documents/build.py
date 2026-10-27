"""Применение выполняет UI; реальный compiler связан с operation ID и digest."""

import asyncio
from uuid import uuid4

import httpx

from scripts.harness.live.documents.fixture import PATH, post, scoped_ui
from service.infrastructure import workspace_client
from service.settings import config
from service.shared.document_review import operation_build_id


async def apply_and_build(client, prefix, ref, scope, proposal_id, before, old_project):
    response = await client.get(prefix + "/documents/proposals/" + proposal_id)
    assert response.status_code == 200
    review = response.json()
    assert review["patch_version"] == 2 and not review["stale"]
    assert review["before"] == before["draft"] and len(review["draft"]["blocks"]) == 3
    unchanged = before["draft"]["blocks"][1]
    assert review["draft"]["blocks"][-1] == unchanged
    lease = await post(client, prefix + "/leases/acquire", {"path": PATH})
    applied = await post(
        client,
        prefix + "/documents/authoring/edit",
        {
            "path": PATH,
            "draft": review["draft"],
            "authoring_version": review["authoring_version"],
            "draft_digest": review["draft_digest"],
            "expected_revision": review["expected_revision"],
            "fence": lease["fence"],
        },
    )
    assert applied["authoring_version"] == 3 and applied["draft_digest"] != before["draft_digest"]
    state = await workspace_client.document_authoring_state(ref, path=PATH)
    assert len(state["draft"]["blocks"]) == 3 and state["draft"]["blocks"][-1] == unchanged
    project = await workspace_client.document_project_status(ref, path=PATH)
    assert project["source_digest"] != old_project["source_digest"]
    scoped = scoped_ui(ref, scope.user_id)
    operation = str(uuid4())
    build = await workspace_client.start_document_build(
        scoped,
        path=PATH,
        expected_revision=applied["revision"],
        fence=lease["fence"],
        final=False,
        operation_id=operation,
    )
    assert build["build_id"] == operation_build_id(ref["workspace_id"], operation)
    replay = await workspace_client.start_document_build(
        scoped,
        path=PATH,
        expected_revision=applied["revision"],
        fence=lease["fence"],
        final=False,
        operation_id=operation,
    )
    assert all(
        replay[key] == build[key]
        for key in (
            "build_id",
            "source_revision",
            "source_digest",
            "draft_digest",
            "authoring_version",
        )
    )
    async with asyncio.timeout(180):
        while build["state"] not in {"preview_ready", "ready", "failed", "cancelled"}:
            await asyncio.sleep(0.1)
            build = await workspace_client.document_build_status(ref, build_id=build["build_id"])
    if build["state"] != "preview_ready":
        print(
            {"build_failure_code": build.get("failure_code"), "state": build["state"]}, flush=True
        )
    assert build["state"] == "preview_ready" and not build["final"]
    assert build["authoring_version"] == 3 and build["draft_digest"] == applied["draft_digest"]
    assert build["source_digest"] == project["source_digest"] and build["page_count"] == 3
    pdf = next(item for item in build["artifacts"] if item["role"] == "pdf")
    download = await workspace_client.stream_document_artifact(
        ref,
        build_id=build["build_id"],
        artifact_id=pdf["artifact_id"],
    )
    payload = b"".join([chunk async for chunk in download.chunks()])
    assert payload.startswith(b"%PDF") and len(payload) == pdf["size"]
    assert (await workspace_client.document_project_status(ref, path=PATH))["latest_build"][
        "build_id"
    ] == build["build_id"]
    # Новый PDF не подтверждает исполнение прошлой review-only задачи задним числом.
    stale = await client.get(prefix + "/documents/proposals/" + proposal_id)
    assert stale.status_code == 200 and stale.json()["stale"]
    assert config.agents.workspace_url == "http://workspace:8082"
    await post(client, prefix + "/leases/release", {"path": PATH, "fence": lease["fence"]})
    return build


async def assert_ack_boundaries():
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            "http://workspace:8082/__harness_acceptance__/workspace",
            headers={"Authorization": "Bearer " + config.agents.workspace_api_key},
        )
    assert response.status_code == 200
    assert response.json() == {
        "lost": {"proposals": 1, "builds": 1},
        "attempts": {"proposals": 1, "builds": 2},
        "identities": {"proposals": 1, "builds": 1},
    }
