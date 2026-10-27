"""Opt-in authenticated Work + private HTTP checkpoint consistency, without model calls."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from uuid import UUID, uuid4

import httpx
import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("S37_LIVE_CHECKPOINT_HTTP") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
        reason="explicit dev checkpoint HTTP acceptance",
    ),
]


async def _private_call(thread_id, session, path, body):
    # The capability and ownership token never leave this backend process. Only
    # this test's synthetic checkpoint fields and bounded outcomes are returned.
    arguments = json.dumps([thread_id, session, path, body], ensure_ascii=True)
    probe = f"""
import asyncio,json,logging
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.cache.manager import RedisManager
from service.infrastructure import workspace_client as client
from service.services.chat.presentation.routers.chat_api.workspace.access import _ui_capability
arguments=json.loads({arguments!r})
async def main():
 config=Config(); manager=RedisManager(config.redis)
 try:
  thread,actor,path,body=arguments
  ref=await client.read_binding(manager.get_client(),thread)
  assert ref and ref.get('thread_id')==thread
  async with PgConnector(config.pg).get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {{'email':'s37-e2e-391e5206659a3654@example.com'}})
  assert owner and str(owner)==str(ref.get('user_id'))
  if path=='__cleanup__':
   await client.release_workspace(manager.get_client(),thread)
   assert await client.read_binding(manager.get_client(),thread) is None
   try:
    await client._call(ref,'files/tree',{{}})
   except client.WorkspaceGone:
    pass
   else:
    raise AssertionError('workspace_cleanup_not_proven')
   print(json.dumps({{'outcome':'released'}})); return
  scoped={{**ref,'coordination_capability':_ui_capability(ref,str(owner),actor)}}
  result=await client._call(scoped,path,body,bounded_errors=frozenset({{'source_changed'}}))
  assert isinstance(result,dict)
  safe={{key:result[key] for key in ('outcome','revision','path','checkpoint') if key in result}}
  print(json.dumps(safe,separators=(',',':')))
 except client.WorkspaceConflict:
  print(json.dumps({{'outcome':'conflict'}}))
 except client.WorkspaceRequestRejected as error:
  print(json.dumps({{'outcome':'rejected','code':error.code}}))
 except Exception:
  print(json.dumps({{'outcome':'probe_failed'}})); raise SystemExit(1)
 finally:
  await manager.close()
asyncio.run(main())
"""
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=probe.encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, "checkpoint_private_boundary_failed"
    return json.loads(result.stdout)


async def _agent_checkpoint(checkpoint=None):
    payload = json.dumps(checkpoint)
    probe = f"""
import asyncio,json,logging
from types import SimpleNamespace
logging.disable(logging.CRITICAL)
from service.domain.documents import authoring,normalize_brief
from service.domain.documents.semantic.outline import parse_document_outline
from service.domain.documents.authoring.checkpoint import restore_authoring_checkpoint
value=json.loads({payload!r})
async def forbidden(*args,**kwargs):
 raise AssertionError('completed_checkpoint_must_not_call_model')
authoring.invoke_model_call=forbidden
async def main():
 global value
 if value is None:
  outline=parse_document_outline({{'title':'Checkpoint','sections':[{{
   'title':'Introduction','purpose':'Explain','block_kinds':['paragraph'],'source_ids':[]
  }}]}},allowed_source_ids=frozenset())
  assert outline and len(outline.sections)==1
  value={{'schema_version':1,'stage':'complete','draft_version':3,
   'outline':outline.payload(),'blocks':[{{'block_id':'paragraph_001','kind':'paragraph',
    'text':'accepted'}}],'accepted_section_ids':[outline.sections[0].section_id],
   'repair_used':True}}
 restored=restore_authoring_checkpoint(value,citations=None,evidence=None)
 assert restored is not None
 result=await authoring.author_semantic_draft_result(normalize_brief('Create a report'),
  'no-model-call',execution=SimpleNamespace(provider_snapshot=None),
  citations=None,resume=restored)
 assert result.accepted and result.draft.version==3
 print(json.dumps({{'checkpoint':restored.payload(),'version':result.draft.version,
  'blocks':[block.text for block in result.draft.blocks]}},separators=(',',':')))
try:
 asyncio.run(main())
except Exception:
 print('{{"outcome":"agent_resume_failed"}}'); raise SystemExit(1)
"""
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-agents-1", "python", "-"],
        input=probe.encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, "agent_checkpoint_resume_failed"
    return json.loads(result.stdout)


async def test_http_resume_keeps_version_and_rejects_subsequent_user_edit():
    actor = uuid4().hex
    async with httpx.AsyncClient(
        base_url="http://localhost:8001",
        cookies={"auth_token": os.environ["E2E_AUTH_TOKEN"]},
        headers={"X-Workspace-Session": actor},
        timeout=60,
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 checkpoint HTTP"})
        assert created.status_code == 201, "thread_create_failed"
        thread = str(UUID(created.json()["thread_id"]))
        allocated = False
        renewal = None
        try:
            base = f"/api/chats/{thread}"
            passive = await client.get(base + "/work")
            assert passive.status_code == 200 and passive.json()["workspace"]["state"] == "absent"
            activated = await client.post(base + "/work/activate")
            assert activated.status_code == 200, "workspace_activate_failed"
            allocated = True
            revision = activated.json()["workspace"]["revision"]
            project_path = "documents/checkpoint-http"
            leased = await client.post(
                base + "/workspace/leases/acquire", json={"path": project_path}
            )
            assert leased.status_code == 200, "project_lease_failed"
            fence = leased.json()["fence"]

            async def renew():
                while True:
                    await asyncio.sleep(10)
                    renewed = await client.post(
                        base + "/workspace/leases/renew",
                        json={"path": project_path, "fence": fence},
                    )
                    assert renewed.status_code == 200, "lease_renewal_failed"

            renewal = asyncio.create_task(renew())
            project = await client.post(
                base + "/workspace/documents",
                json={
                    "path": project_path,
                    "profile_id": "generic_document",
                    "mode": "draft",
                    "expected_revision": revision,
                    "fence": fence,
                },
            )
            assert project.status_code == 200, "project_create_failed"
            revision = project.json()["revision"]
            checkpoint = (await _agent_checkpoint())["checkpoint"]
            draft = {
                "schema_version": 1,
                "version": 3,
                "title": "Checkpoint",
                "blocks": checkpoint["blocks"],
            }
            identity = {"request_digest": "a" * 64, "evidence_digest": "b" * 64}
            saved = await _private_call(
                thread,
                actor,
                "documents/authoring/checkpoint",
                {
                    "path": project_path,
                    "checkpoint": checkpoint,
                    **identity,
                    "expected_revision": revision,
                    "coordination_fence": fence,
                },
            )
            assert saved["outcome"] == "checkpointed"
            digest = hashlib.sha256(
                json.dumps(
                    draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            files = {
                "main.tex": "\\documentclass{article}\n\\begin{document}accepted\\end{document}",
                "content/body.tex": "accepted",
                ".gpthub-authoring.json": json.dumps(
                    {"draft_version": 3, "draft_digest": digest, "draft": draft}
                ),
            }
            published = await client.post(
                base + "/workspace/documents/source",
                json={
                    "path": project_path,
                    "files": files,
                    "authoring_version": 3,
                    "draft_digest": digest,
                    "expected_revision": revision,
                    "fence": fence,
                },
            )
            assert published.status_code == 200, "source_publication_failed"
            revision = published.json()["revision"]
            for _ in range(2):
                resumed = await _private_call(
                    thread, actor, "documents/authoring/checkpoint/latest", identity
                )
                assert resumed["revision"] == revision
                assert resumed["checkpoint"]["draft_version"] == 3
                assert resumed["checkpoint"]["blocks"] == draft["blocks"]
                accepted = await _agent_checkpoint(resumed["checkpoint"])
                assert accepted["version"] == 3 and accepted["blocks"] == ["accepted"]
                current = await client.post(
                    base + "/workspace/file", json={"path": project_path + "/main.tex"}
                )
                assert current.status_code == 200
                assert current.json()["revision"] == resumed["revision"]
                assert current.json()["content"] == files["main.tex"]
            edited = files["main.tex"].replace("accepted", "USER EDIT MUST SURVIVE")
            assert not renewal.done(), "lease_renewal_stopped"
            file_lease = await client.post(
                base + "/workspace/leases/acquire", json={"path": project_path + "/main.tex"}
            )
            assert file_lease.status_code == 200, "file_lease_failed"
            changed = await client.post(
                base + "/workspace/write",
                json={
                    "path": project_path + "/main.tex",
                    "content": edited,
                    "expected_revision": revision,
                    "fence": file_lease.json()["fence"],
                },
            )
            assert changed.status_code == 200, "user_edit_failed"
            refused = await _private_call(
                thread, actor, "documents/authoring/checkpoint/latest", identity
            )
            assert refused == {"outcome": "rejected", "code": "source_changed"}
            stale = await client.post(
                base + "/workspace/documents/source",
                json={
                    "path": project_path,
                    "files": files,
                    "authoring_version": 3,
                    "draft_digest": digest,
                    "expected_revision": revision,
                    "fence": fence,
                },
            )
            assert stale.status_code == 409, "stale_source_was_accepted"
            retained = await client.post(
                base + "/workspace/file", json={"path": project_path + "/main.tex"}
            )
            assert retained.status_code == 200 and retained.json()["content"] == edited
        finally:
            if renewal is not None:
                renewal.cancel()
                await asyncio.gather(renewal, return_exceptions=True)
            if allocated:
                assert (await _private_call(thread, actor, "__cleanup__", {}))[
                    "outcome"
                ] == "released"
            removed = await client.delete(f"/api/chats/{thread}")
            assert removed.status_code in {200, 204}, "fixture_cleanup_failed"
