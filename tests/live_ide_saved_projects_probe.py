"""Opt-in native dev Save -> real expiry -> restore, only a labelled QA project.

Run via stdin inside gpthub-dev-backend-1. Never changes global TTL, existing
projects, remote Git or billing; fixture TTL is 35 seconds for real expiry,
180 seconds for the optional cleanup-only case. Global TTL never changes.
"""

import asyncio
import json
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from service.composition.storage import build_file_storage
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.checkpoints.budget import CheckpointStorageBudget
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.checkpoints.repository import IdeCheckpointRepository
from service.services.chat.persistence.ide.repositories import IdeRepositoryRepository
from service.services.chat.persistence.ide.runtime import IdeRuntimeRepository
from service.settings import config

CRASH_WRITER = r"""
import asyncio,json,logging,os,sys
from dataclasses import replace
from uuid import UUID
from service.settings import config
from service.composition.storage import build_file_storage
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.services.chat.domain.ide.checkpoints.budget import CheckpointStorageBudget
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.checkpoints.repository import IdeCheckpointRepository
async def write_then_exit():
 assert os.environ.get('IDE_SAVED_PROJECTS_DEV_ACCEPTANCE')=='1'
 assert any(os.environ.get(key)=='1' for key in (
  'IDE_SAVED_PROJECTS_CRASH_RECOVERY','IDE_SAVED_PROJECTS_ABANDON_ONLY'))
 logging.disable(logging.CRITICAL)
 data=json.loads(sys.stdin.readline())
 scope=RepositoryScope(*(UUID(data[key]) for key in ('thread_id','user_id','repository_id')))
 connector=PgConnector(config.pg)
 ledger=IdeCheckpointRepository(connector)
 original=await ledger.get_owned(scope,UUID(data['original_id']))
 assert original is not None and original.is_current
 target=replace(original.intent,
  blob=replace(original.intent.blob,checkpoint_id=UUID(data['checkpoint_id'])),
  base_checkpoint_id=original.intent.blob.checkpoint_id)
 assert target.blob.key_for(scope)!=original.intent.blob.key_for(scope)
 options=config.ide_checkpoints
 if data.get('mode')=='blocked_save':
  from service.services.chat.application.ide.checkpoints.service import IdeCheckpointService
  from service.services.chat.application.ide.checkpoints import retention as cleanup_app
  from service.services.chat.persistence.ide.checkpoints import retention as cleanup_db
  class DelayedStorage(IdeCheckpointStorage):
   async def put(self,scope,blob,source):
    print(json.dumps({'stage':'reserved_before_put'}),flush=True)
    assert (await asyncio.to_thread(sys.stdin.readline)).strip()=='continue'
    await super().put(scope,blob,source)
  storage=DelayedStorage(build_file_storage(config),max_bytes=options.max_snapshot_bytes)
  assert storage.namespace==target.storage_namespace
  service=IdeCheckpointService(ledger,storage,historical=True,
   budget=CheckpointStorageBudget(options.max_user_bytes,options.max_snapshot_bytes,
    options.max_pending_per_repository),retention=cleanup_app.IdeCheckpointRetentionService(
     cleanup_db.IdeCheckpointRetentionRepository(connector),storage))
  async with storage.open(scope,original.intent.blob) as source:
   result=await service.save(scope,target,source)
  current=await ledger.get_owned(scope,target.blob.checkpoint_id)
  assert result.state=='retired' and current.state=='retired'
  assert current.upload_settled and current.collected
  print(json.dumps({'stage':'late_writer_collected'}),flush=True)
  await connector._engine.dispose()
  return
 admitted=await ledger.reserve(target,budget=CheckpointStorageBudget(
  options.max_user_bytes,options.max_snapshot_bytes,options.max_pending_per_repository))
 assert admitted.dispatch
 storage=IdeCheckpointStorage(build_file_storage(config),max_bytes=options.max_snapshot_bytes)
 assert storage.namespace==target.storage_namespace
 async with storage.open(scope,original.intent.blob) as source:
  await storage.put(scope,target.blob,source)
 print(json.dumps({'stage':'uploaded_before_receipt'}),flush=True)
 # Intentional process loss: no settlement receipt, publication or graceful exit.
 os._exit(91)
try:
 asyncio.run(write_then_exit())
except Exception as error:
 print(json.dumps({'stage':'writer_failed','type':type(error).__name__}),flush=True)
 raise SystemExit(1) from None
"""


async def main() -> None:
    if os.environ.get("IDE_SAVED_PROJECTS_DEV_ACCEPTANCE") != "1":
        raise RuntimeError("explicit_dev_acceptance_required")
    assert config.ide_checkpoints.enabled
    logging.disable(logging.CRITICAL)
    token = json.loads(Path("/tmp/.env.s38").read_text())["token"]
    actor = uuid4().hex
    async with httpx.AsyncClient(
        base_url="http://localhost:8000",
        timeout=100,
        cookies={"auth_token": token},
        headers={"X-Workspace-Session": actor},
    ) as http:

        async def call(method, path, data=None, expected=200):
            reply = await http.request(method, path, json=data)
            if reply.status_code != expected:
                # Closed protocol code only; never SDK/validation/raw response bodies.
                body = reply.json()
                detail = body.get("detail") or body.get("error", {}).get("code")
                if detail == "http_error":
                    detail = body.get("error", {}).get("message")
                code = (
                    detail if isinstance(detail, str) and detail.startswith("ide_") else "unknown"
                )
                print(
                    json.dumps(
                        {
                            "stage": path.rsplit("/", 1)[-1],
                            "method": method,
                            "status": reply.status_code,
                            "code": code,
                        }
                    )
                )
                raise RuntimeError("native_saved_projects_stage_failed")
            return reply.json()

        me = await call("GET", "/api/profile/me")
        user_id = UUID(str(me.get("user_id") or me.get("id")))
        chat = await call(
            "POST", "/api/chats/", {"title": "QA IDE native Save restore"}, expected=201
        )
        thread_id = UUID(chat["thread_id"])
        base = f"/api/chats/{thread_id}/ide/repositories"
        descriptor = await call(
            "POST",
            base,
            {
                "name": "QA native saved project",
                "creation_intent_id": str(uuid4()),
                "create_thread_if_missing": True,
            },
        )
        repository_id = UUID(descriptor["repository_id"])
        scope = RepositoryScope(thread_id, user_id, repository_id)
        connector = PgConnector(config.pg)
        native = IdeWorkspaceClient(config.agents)
        # Fixture-local policy only. Production/public clients cannot choose TTL.
        extended = any(
            os.environ.get(name) == "1"
            for name in (
                "IDE_SAVED_PROJECTS_CLEANUP_ONLY",
                "IDE_SAVED_PROJECTS_CRASH_RECOVERY",
                "IDE_SAVED_PROJECTS_ABANDON_ONLY",
            )
        )
        native._ttl = 180 if extended else 35
        runtime = IdeRuntimeService(
            IdeRepositoryRepository(connector), IdeRuntimeRepository(connector), native
        )
        prepared = await runtime.provision(scope)
        assert prepared["workspace"]["state"] == "ready"
        root = f"{base}/{repository_id}"
        tree = await call("POST", f"{root}/files/tree", {"path": ""})
        generation = tree["generation"]
        await call("POST", f"{root}/git", {"operation": "init", "generation": generation})
        lease = await call(
            "POST",
            f"{root}/files/lease",
            {
                "path": "README.md",
                "generation": generation,
                "action": "acquire",
            },
        )
        content = "# Native saved project\n\nДанные переживают завершение среды.\n"
        await call(
            "POST",
            f"{root}/files/write",
            {
                "path": "README.md",
                "generation": generation,
                "operation": "file",
                "content": content,
                "expected_digest": None,
                "fence": lease["fence"],
            },
        )
        await call(
            "POST",
            f"{root}/files/lease",
            {
                "path": "README.md",
                "generation": generation,
                "action": "release",
                "fence": lease["fence"],
            },
        )
        assert (await call("GET", f"{root}/checkpoints/capabilities"))["enabled"] is True
        intent = {
            "checkpoint_id": str(uuid4()),
            "base_checkpoint_id": None,
            "generation": generation,
        }
        usage_before = (await call("GET", f"{root}/checkpoints"))["usage"]["used_bytes"]
        saved = await call("POST", f"{root}/checkpoints", intent)
        assert saved["state"] == "published" and saved["is_current"] is True
        replay = await call("POST", f"{root}/checkpoints", intent)
        assert replay["checkpoint_id"] == intent["checkpoint_id"] and replay["state"] == "published"
        history = await call("GET", f"{root}/checkpoints")
        assert len(history["items"]) == 1
        assert history["usage"]["used_bytes"] == usage_before + saved["size_bytes"]
        if os.environ.get("IDE_SAVED_PROJECTS_ABANDON_ONLY") == "1":
            checkpoint_id = uuid4()
            payload = {
                **{key: str(value) for key, value in scope.params().items()},
                "original_id": intent["checkpoint_id"],
                "checkpoint_id": str(checkpoint_id),
                "mode": "blocked_save",
            }
            writer = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                CRASH_WRITER,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                assert writer.stdin is not None and writer.stdout is not None
                writer.stdin.write((json.dumps(payload) + "\n").encode())
                await writer.stdin.drain()
                ready = await asyncio.wait_for(writer.stdout.readline(), timeout=45)
                if ready and json.loads(ready).get("stage") == "writer_failed":
                    failure = json.loads(ready)
                    assert failure["type"] in {
                        "AssertionError",
                        "TypeError",
                        "AttributeError",
                        "IdeCheckpointError",
                    }
                    print(json.dumps(failure))
                assert json.loads(ready) == {"stage": "reserved_before_put"}
                target = f"{root}/checkpoints/{checkpoint_id}"
                pending = await call("GET", target)
                assert pending["can_abandon"] and not pending["can_discard"]
                revoked = await call("POST", f"{target}/abandon", {})
                assert revoked["state"] == "retired" and not revoked["collected"]
                await call("POST", f"{target}/discard", {}, expected=409)
                current = await call(
                    "POST", f"{root}/files/read", {"path": "README.md", "generation": generation}
                )
                lease = await call(
                    "POST",
                    f"{root}/files/lease",
                    {"path": "README.md", "generation": generation, "action": "acquire"},
                )
                newer_content = content + "\nНовая версия после отмены.\n"
                await call(
                    "POST",
                    f"{root}/files/write",
                    {
                        "path": "README.md",
                        "generation": generation,
                        "operation": "file",
                        "content": newer_content,
                        "expected_digest": current["digest"],
                        "fence": lease["fence"],
                    },
                )
                await call(
                    "POST",
                    f"{root}/files/lease",
                    {
                        "path": "README.md",
                        "generation": generation,
                        "action": "release",
                        "fence": lease["fence"],
                    },
                )
                next_id = str(uuid4())
                next_saved = await call(
                    "POST",
                    f"{root}/checkpoints",
                    {
                        "checkpoint_id": next_id,
                        "base_checkpoint_id": intent["checkpoint_id"],
                        "generation": generation,
                    },
                )
                assert next_saved["is_current"]
                writer.stdin.write(b"continue\n")
                await writer.stdin.drain()
                output, _diagnostics = await asyncio.wait_for(writer.communicate(), timeout=45)
                assert writer.returncode == 0 and json.loads(output) == {
                    "stage": "late_writer_collected"
                }
                terminal = await call("GET", target)
                assert terminal["state"] == "retired" and terminal["collected"]
                final = await call("GET", f"{root}/checkpoints")
                assert len(final["items"]) == 2 and final["items"][0]["checkpoint_id"] == next_id
                assert (
                    final["usage"]["used_bytes"]
                    == usage_before + saved["size_bytes"] + next_saved["size_bytes"]
                )
                read = await call(
                    "POST", f"{root}/files/read", {"path": "README.md", "generation": generation}
                )
                assert read["content"] == newer_content
                print(
                    json.dumps(
                        {
                            "native_abandon": "passed",
                            "new_save_admitted": True,
                            "late_writer_cannot_publish": True,
                            "late_writer_collected": True,
                            "newer_project_file_preserved": True,
                        }
                    )
                )
            finally:
                if writer.returncode is None:
                    writer.kill()
                    await writer.wait()
            await connector._engine.dispose()
            return
        if os.environ.get("IDE_SAVED_PROJECTS_CRASH_RECOVERY") == "1":
            checkpoint_id = uuid4()
            payload = {
                **{key: str(value) for key, value in scope.params().items()},
                "original_id": intent["checkpoint_id"],
                "checkpoint_id": str(checkpoint_id),
            }
            writer = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                CRASH_WRITER,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                output, _diagnostics = await asyncio.wait_for(
                    writer.communicate(json.dumps(payload).encode()), timeout=45
                )
            except BaseException:
                if writer.returncode is None:
                    writer.kill()
                await writer.wait()
                raise
            assert writer.returncode == 91
            assert json.loads(output) == {"stage": "uploaded_before_receipt"}
            target = f"{root}/checkpoints/{checkpoint_id}"
            observed = await call("GET", target)
            assert observed["state"] == "pending" and observed["can_discard"] is False
            denied = await call("POST", f"{target}/discard", {}, expected=409)
            assert denied["error"]["code"] == "ide_checkpoint_not_discardable"
            recovered = await call("POST", f"{target}/reconcile", {})
            assert recovered["state"] == "published" and recovered["is_current"] is True
            replay = await call(
                "POST",
                f"{root}/checkpoints",
                {
                    "checkpoint_id": str(checkpoint_id),
                    "base_checkpoint_id": intent["checkpoint_id"],
                    "generation": generation,
                },
            )
            assert replay["state"] == "published" and replay["checkpoint_id"] == str(checkpoint_id)
            fresh_ledger = IdeCheckpointRepository(PgConnector(config.pg, force_new=True))
            recovered_record = await fresh_ledger.get_owned(scope, checkpoint_id)
            assert recovered_record.is_current and not recovered_record.upload_settled
            final = await call("GET", f"{root}/checkpoints")
            assert len(final["items"]) == 2
            assert final["usage"]["used_bytes"] == usage_before + 2 * saved["size_bytes"]
            read = await call(
                "POST", f"{root}/files/read", {"path": "README.md", "generation": generation}
            )
            assert read["content"] == content
            print(
                json.dumps(
                    {
                        "native_crash_recovery": "passed",
                        "writer_exit": 91,
                        "pending_to_published": True,
                        "receipt_not_invented": True,
                        "snapshot_count": len(final["items"]),
                        "project_file_preserved": True,
                    }
                )
            )
            await fresh_ledger.connector._engine.dispose()
            await connector._engine.dispose()
            return
        if os.environ.get("IDE_SAVED_PROJECTS_CLEANUP_ONLY") == "1":
            ledger = IdeCheckpointRepository(connector)
            original = await ledger.get_owned(scope, UUID(intent["checkpoint_id"]))
            assert original is not None and original.is_current
            failed = replace(
                original.intent,
                blob=replace(original.intent.blob, checkpoint_id=uuid4()),
                base_checkpoint_id=original.intent.blob.checkpoint_id,
            )
            options = config.ide_checkpoints
            admission = await ledger.reserve(
                failed,
                budget=CheckpointStorageBudget(
                    options.max_user_bytes,
                    options.max_snapshot_bytes,
                    options.max_pending_per_repository,
                ),
            )
            assert admission.dispatch
            storage = IdeCheckpointStorage(
                build_file_storage(config), max_bytes=options.max_snapshot_bytes
            )
            assert storage.namespace == failed.storage_namespace
            async with storage.open(scope, original.intent.blob) as source:
                await storage.put(scope, failed.blob, source)
            target = f"{root}/checkpoints/{failed.blob.checkpoint_id}"
            assert (await call("GET", target))["can_discard"] is False
            await call("POST", f"{target}/discard", {}, expected=409)
            # Actual SDK put has settled. Simulate interruption after retire commit,
            # before collection; no unknown writer is declared safe by elapsed time.
            assert (await ledger.mark_upload_settled(failed)).upload_settled
            retired, allowed = await ledger.abandon_pending(scope, failed.blob.checkpoint_id)
            assert allowed and retired.state == "retired"
            before = await call("GET", f"{root}/checkpoints")
            assert any(
                row["checkpoint_id"] == str(failed.blob.checkpoint_id)
                and row["state"] == "retired"
                and row["can_discard"]
                for row in before["items"]
            )
            cleaned = await call("POST", f"{target}/discard", {})
            assert cleaned["collected"] is True and cleaned["cleanup_pending"] is False
            assert (await call("POST", f"{target}/discard", {}))["collected"] is True
            final = await call("GET", f"{root}/checkpoints")
            assert len(final["items"]) == 1
            assert final["usage"]["used_bytes"] == usage_before + saved["size_bytes"]
            assert final["items"][0]["checkpoint_id"] == intent["checkpoint_id"]
            async with storage.open(scope, original.intent.blob) as source:
                assert source.read(1)
            read = await call(
                "POST", f"{root}/files/read", {"path": "README.md", "generation": generation}
            )
            assert read["content"] == content
            print(
                json.dumps(
                    {
                        "native_cleanup": "passed",
                        "unsettled_refused": True,
                        "retired_visible": True,
                        "exact_bytes_released": failed.blob.size,
                        "published_version_preserved": True,
                        "project_file_preserved": True,
                    }
                )
            )
            await connector._engine.dispose()
            return
        rejected = await http.post(
            f"{root}/restores",
            json={
                "restore_id": str(uuid4()),
                "checkpoint_id": intent["checkpoint_id"],
                "base_generation": generation,
            },
        )
        assert rejected.status_code == 409
        print(
            json.dumps(
                {"save": "published", "same_intent_replay": True, "live_restore_refused": True}
            ),
            flush=True,
        )
        for _ in range(22):
            observed = await call("GET", f"{root}/runtime")
            if observed["workspace"]["state"] == "expired":
                break
            await asyncio.sleep(2)
        else:
            raise RuntimeError("fixture_expiry_not_observed")
        restore = {
            "restore_id": str(uuid4()),
            "checkpoint_id": intent["checkpoint_id"],
            "base_generation": generation,
        }
        restored = await call("POST", f"{root}/restores", restore)
        assert restored["state"] == "published" and restored["active"] is True
        assert restored["generation"] != generation
        again = await call("POST", f"{root}/restores", restore)
        assert again["active"] is True and again["generation"] == restored["generation"]
        read = await call(
            "POST",
            f"{root}/files/read",
            {"path": "README.md", "generation": restored["generation"]},
        )
        assert read["content"] == content
        final = await call("GET", f"{root}/checkpoints")
        assert len(final["items"]) == 1 and final["last_restore"]["active"] is True
        assert "allocation_id" not in json.dumps(final) and "storage_namespace" not in json.dumps(
            final
        )
        print(
            json.dumps(
                {
                    "restore": "active",
                    "real_expiry": True,
                    "utf8_bytes_preserved": True,
                    "versions": len(final["items"]),
                    "thread_id": str(thread_id),
                }
            )
        )
        await connector._engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        print(json.dumps({"status": "failed", "code": "native_saved_projects_acceptance_failed"}))
        raise SystemExit(1) from None
