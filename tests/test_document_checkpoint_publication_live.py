"""Opt-in real shell/atomic source+checkpoint exercise in an isolated offline container."""

import asyncio
import hashlib
import json
import os
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest
from application.documents.checkpoint_storage import checkpoint_digest_command
from application.documents.checkpoints import DocumentCheckpointService
from application.documents.projects import DocumentProjectError
from application.documents.source_recovery import SourcePublicationRecovery
from application.documents.sources import DocumentSourceService

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("S37_LIVE_CHECKPOINT") != "1", reason="isolated Docker shell acceptance"
    ),
]


class _PublisherStopped(BaseException):
    """Simulate process death: production Exception rollback must not run."""


async def _docker(*arguments, payload=None):
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", *arguments],
        input=payload,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, "checkpoint_container_operation_failed"
    return result.stdout.decode().strip()


@pytest.mark.parametrize(
    "scenario",
    [
        "published",
        "partial_resume",
        "snapshot_rollback",
        "user_edit",
        "kill_before_exchange",
        "kill_after_exchange",
        "stop_after_snapshot",
        "exchange_unavailable",
    ],
)
async def test_checkpoint_anchor_travels_with_managed_source_publication(scenario):
    name = "s37-checkpoint-" + uuid4().hex
    container = await _docker(
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "gpthub.s37.checkpoint=1",
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
        os.getenv("S37_CHECKPOINT_IMAGE", "gpthub-workspace-runtime:latest"),
        "sleep",
        "180",
    )
    try:

        async def run(_item, command, *, stdin_payload=None):
            if (
                stdin_payload is not None
                and "renameat2" in command
                and scenario == "exchange_unavailable"
            ):
                command = command.replace(
                    "rename=library.renameat2;",
                    "raise RuntimeError('source_exchange_failed');",
                    1,
                )
            if (
                stdin_payload is not None
                and "renameat2" in command
                and scenario.startswith("kill_")
            ):
                if scenario == "kill_after_exchange":
                    command = command.replace(
                        "; mv /workspace/.gpthub-document/authoring-",
                        "; kill -KILL $$; mv /workspace/.gpthub-document/authoring-",
                        1,
                    )
                else:
                    # Marker creation immediately precedes the exchange invocation.
                    boundary = command.index("renameat2")
                    prefix = command.rfind("python -c ", 0, boundary)
                    command = command[:prefix] + "kill -KILL $$; " + command[prefix:]
                try:
                    await _docker(
                        "exec", "-i", container, "sh", "-c", command, payload=stdin_payload
                    )
                except AssertionError:
                    raise _PublisherStopped() from None
                raise AssertionError("source_fault_seam_not_reached")
            return SimpleNamespace(
                stdout=await _docker(
                    "exec",
                    "-i",
                    container,
                    "sh",
                    "-c",
                    command,
                    payload=stdin_payload,
                )
            )

        async def manifest(*arguments):
            return {}, object()

        snapshot_calls = []

        async def snapshot(*arguments):
            snapshot_calls.append(arguments[-1])
            if scenario == "snapshot_rollback":
                return {"committed": False, "reason": "failed"}
            output = (
                await run(
                    None,
                    "git -C /workspace add -A; "
                    "if git -C /workspace diff --cached --quiet; then echo __NO_CHANGES__; "
                    "else git -C /workspace commit -q -m document_authoring; echo __COMMITTED__; fi; "
                    "git -C /workspace rev-parse HEAD",
                )
            ).stdout
            if scenario == "stop_after_snapshot" and len(snapshot_calls) == 1:
                raise _PublisherStopped()
            return {
                "committed": "__COMMITTED__" in output,
                "reason": "no_changes" if "__NO_CHANGES__" in output else "",
                "revision": output.splitlines()[-1],
            }

        async def revision(*arguments):
            return (await run(None, "git -C /workspace rev-parse HEAD")).stdout

        item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"))
        await run(
            item,
            "mkdir -p /workspace/documents/test; echo scaffold > /workspace/documents/test/main.tex",
        )
        await run(
            item,
            "git -C /workspace init -q; git -C /workspace config user.email test@example.invalid; "
            "git -C /workspace config user.name Test; "
            "printf '.gpthub-document/\\n' > /workspace/.git/info/exclude; "
            "git -C /workspace add -A; git -C /workspace commit -q -m agent_run",
        )
        checkpoints = DocumentCheckpointService(run, SimpleNamespace(manifest=manifest))
        checkpoint = {
            "schema_version": 1,
            "stage": "complete",
            "outline": {
                "title": "Test",
                "sections": [
                    {
                        "section_id": "introduction_01_27d86ede3b",
                        "title": "Introduction",
                        "purpose": "Explain",
                        "block_kinds": ["paragraph"],
                        "source_ids": [],
                    }
                ],
            },
            "blocks": [
                {"block_id": "stable", "kind": "paragraph", "text": "initial accepted content"}
            ],
            "accepted_section_ids": ["introduction_01_27d86ede3b"],
            "repair_used": False,
        }
        await checkpoints.write(
            item,
            path="documents/test",
            checkpoint=checkpoint,
            revision="r1",
            request_digest="a" * 64,
            evidence_digest="b" * 64,
        )
        initial = await checkpoints.latest(item, request_digest="a" * 64, evidence_digest="b" * 64)
        assert initial["checkpoint"]["blocks"] == checkpoint["blocks"]
        if scenario == "partial_resume":
            await checkpoints.write(
                item,
                path="documents/test",
                checkpoint={**checkpoint, "stage": "section_authoring"},
                revision="r1",
                request_digest="a" * 64,
                evidence_digest="b" * 64,
            )
            partial = await DocumentCheckpointService(
                run, SimpleNamespace(manifest=manifest)
            ).latest(item, request_digest="a" * 64, evidence_digest="b" * 64)
            assert partial["checkpoint"]["stage"] == "section_authoring"
            await checkpoints.write(
                item,
                path="documents/test",
                checkpoint=checkpoint,
                revision="r1",
                request_digest="a" * 64,
                evidence_digest="b" * 64,
            )
        draft = {
            "schema_version": 1,
            "version": 2,
            "title": "Test",
            "blocks": [{"block_id": "stable", "kind": "paragraph", "text": "accepted"}],
        }
        digest = hashlib.sha256(
            json.dumps(draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        files = {
            "main.tex": "managed source",
            "content/body.tex": "accepted",
            ".gpthub-authoring.json": json.dumps(
                {"draft_version": 2, "draft_digest": digest, "draft": draft}
            ),
        }
        sources = DocumentSourceService(
            run,
            snapshot,
            revision,
            SimpleNamespace(manifest=manifest),
            checkpoints,
            SourcePublicationRecovery(run, snapshot),
        )
        if scenario == "exchange_unavailable":
            with pytest.raises(DocumentProjectError, match="authoring_publish_failed"):
                await sources.publish(
                    item,
                    path="documents/test",
                    files=files,
                    authoring_version=2,
                    draft_digest=digest,
                )
            assert (await run(item, "cat /workspace/documents/test/main.tex")).stdout == "scaffold"
            assert (
                await checkpoints.latest(item, request_digest="a" * 64, evidence_digest="b" * 64)
                == initial
            )
        elif scenario.startswith("kill_") or scenario == "stop_after_snapshot":
            with pytest.raises(_PublisherStopped):
                await sources.publish(
                    item,
                    path="documents/test",
                    files=files,
                    authoring_version=2,
                    draft_digest=digest,
                )
            current = (await run(item, "cat /workspace/documents/test/main.tex")).stdout
            recovered = DocumentCheckpointService(run, SimpleNamespace(manifest=manifest))
            resumed = await recovered.latest(
                item, request_digest="a" * 64, evidence_digest="b" * 64
            )
            if scenario == "kill_before_exchange":
                assert current == "scaffold"
                assert resumed == initial
            else:
                assert current == "managed source"
                assert resumed["checkpoint"]["blocks"] == draft["blocks"]
                assert resumed["checkpoint"]["draft_version"] == 2
            recovery = SourcePublicationRecovery(run, snapshot)
            counts = await recovery.recover(item)
            assert counts == {"recovered": 1, "pending": 0, "conflicted": 0}
            assert await recovery.recover(item) == {"recovered": 0, "pending": 0, "conflicted": 0}
            expected_snapshots = {
                "kill_before_exchange": 0,
                "kill_after_exchange": 1,
                "stop_after_snapshot": 2,
            }
            assert len(snapshot_calls) == expected_snapshots[scenario]
            assert (await run(item, "git -C /workspace rev-list --count HEAD")).stdout == (
                "1" if scenario == "kill_before_exchange" else "2"
            )
            assert (await run(item, "git -C /workspace status --porcelain")).stdout == ""
            assert (
                await run(
                    item, "find /workspace/.gpthub-document -maxdepth 1 -name 'authoring-*' -type d"
                )
            ).stdout == ""
        elif scenario == "user_edit":
            await run(item, "echo user-edit > /workspace/documents/test/main.tex")
            with pytest.raises(DocumentProjectError, match="source_changed"):
                await sources.publish(
                    item,
                    path="documents/test",
                    files=files,
                    authoring_version=2,
                    draft_digest=digest,
                )
            assert (await run(item, "cat /workspace/documents/test/main.tex")).stdout == "user-edit"
            with pytest.raises(DocumentProjectError, match="source_changed"):
                await checkpoints.latest(item, request_digest="a" * 64, evidence_digest="b" * 64)
        elif scenario == "snapshot_rollback":
            with pytest.raises(DocumentProjectError, match="authoring_publish_failed"):
                await sources.publish(
                    item,
                    path="documents/test",
                    files=files,
                    authoring_version=2,
                    draft_digest=digest,
                )
            assert (await run(item, "cat /workspace/documents/test/main.tex")).stdout == "scaffold"
            restored = await checkpoints.latest(
                item, request_digest="a" * 64, evidence_digest="b" * 64
            )
            assert restored == initial
        else:
            await sources.publish(
                item, path="documents/test", files=files, authoring_version=2, draft_digest=digest
            )
            # Restart the process-local services; only filesystem state survives.
            recovered = DocumentCheckpointService(run, SimpleNamespace(manifest=manifest))
            resumed = await recovered.latest(
                item, request_digest="a" * 64, evidence_digest="b" * 64
            )
            assert resumed["checkpoint"]["blocks"] == draft["blocks"]
            assert resumed["checkpoint"]["draft_version"] == 2
            assert resumed["checkpoint"]["outline"]["title"] == draft["title"]
            assert (
                await run(item, "cat /workspace/documents/test/main.tex")
            ).stdout == "managed source"
    finally:
        ownership = await _docker(
            "inspect", "--format", '{{index .Config.Labels "gpthub.s37.checkpoint"}}', container
        )
        assert ownership == "1", "checkpoint_cleanup_owner_mismatch"
        await _docker("rm", "-f", container)


@pytest.mark.parametrize(
    "case", ["unreadable_file", "unreadable_directory", "symlink", "fifo", "valid", "empty"]
)
async def test_checkpoint_digest_rejects_incomplete_source_inventory(case):
    container = await _docker(
        "run",
        "-d",
        "--name",
        "s37-checkpoint-" + uuid4().hex,
        "--label",
        "gpthub.s37.checkpoint=1",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=65534:65534",
        "--memory=128m",
        "--pids-limit=32",
        "--tmpfs",
        "/workspace:rw,size=32m,mode=1777",
        os.getenv("S37_CHECKPOINT_IMAGE", "gpthub-workspace-runtime:latest"),
        "sleep",
        "180",
    )
    try:
        fixtures = {
            "unreadable_file": "touch blocked; chmod 000 blocked",
            "unreadable_directory": "mkdir blocked; touch blocked/source; chmod 000 blocked",
            "symlink": "ln -s /etc/passwd blocked",
            "fifo": "mkfifo blocked",
            "valid": "touch 'space name.tex' 'кириллица.tex'",
            "empty": "rm main.tex",
        }
        await _docker(
            "exec",
            container,
            "sh",
            "-c",
            "mkdir /workspace/project; cd /workspace/project; touch main.tex; " + fixtures[case],
        )
        command = checkpoint_digest_command("/workspace/project")
        status = await _docker(
            "exec",
            container,
            "sh",
            "-c",
            f"{command} > /workspace/digest.out 2>/dev/null; echo $?",
        )
        if case in {"valid", "empty"}:
            assert status == "0"
            legacy = await _docker(
                "exec",
                container,
                "sh",
                "-c",
                "cd /workspace/project && find . -type f -print0 | sort -z | "
                "xargs -0 sha256sum | sha256sum | cut -d' ' -f1",
            )
            assert await _docker("exec", container, "cat", "/workspace/digest.out") == legacy
        else:
            assert status != "0", "incomplete_source_inventory_was_accepted"
            assert await _docker("exec", container, "cat", "/workspace/digest.out") == ""
    finally:
        assert (
            await _docker(
                "inspect", "--format", '{{index .Config.Labels "gpthub.s37.checkpoint"}}', container
            )
            == "1"
        )
        await _docker("rm", "-f", container)
