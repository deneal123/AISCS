from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from service.infrastructure.agents_client.contracts.events import EventSerializer, EventType
from service.services.chat.application.use_cases.ws_message.handler import (
    HandleWsChatMessageUseCase,
)
from service.services.chat.domain.attachment_meta import user_message_meta
from service.services.chat.domain.confirmation.mode import expire_mode_offer
from service.services.chat.domain.confirmation.offer import (
    ConfirmationOfferError,
    claim_confirmation_offer,
    create_confirmation_offer,
    mark_confirmation_accepted,
)
from service.services.chat.infrastructure.chat_worker.billing.reservation import (
    preflight as reservation,
)
from service.services.chat.infrastructure.chat_worker.context.attachment_evidence import (
    cache_owner_attachment_evidence,
    owner_checked_attachments,
)
from service.services.chat.infrastructure.chat_worker.context.metadata import persistable_meta


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[str(key)] = value
        return True

    async def get(self, key):
        return self.values.get(str(key))

    async def delete(self, *keys):
        for key in keys:
            self.values.pop(str(key), None)


class SyncRedis(FakeRedis):
    """Celery uses synchronous commands; HTTP uses asyncio commands."""

    def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[str(key)] = value
        return True

    def get(self, key):
        return self.values.get(str(key))

    def delete(self, *keys):
        for key in keys:
            self.values.pop(str(key), None)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["broker_ack", "task_id_write"])
async def test_failed_ack_after_enqueue_does_not_unlock_a_second_paid_continuation(
    monkeypatch, failure_stage
):
    from unittest.mock import AsyncMock

    from service.services.chat.application.use_cases.ws_message import handler as module

    redis = FakeRedis()
    owner = str(uuid4())
    anchor = await create_confirmation_offer(
        redis,
        thread_id="thread",
        user_id=owner,
        source_message_id=str(uuid4()),
        text="request",
        selected_model=None,
        route_override=None,
        resolved_category=None,
        input_type="text",
        attachments=None,
        file_ids=None,
    )
    enqueue = []

    def enqueue_with_unknown_ack(**kwargs):
        enqueue.append(kwargs)
        if failure_stage == "broker_ack":
            raise RuntimeError("private-broker-ack-marker")
        return "task"

    jobs = SimpleNamespace(
        job_queue=SimpleNamespace(enqueue_agent_message=enqueue_with_unknown_ack),
        create_chat_job=AsyncMock(return_value=SimpleNamespace(job_id=uuid4())),
        update_job_celery_task_id=AsyncMock(),
    )
    monkeypatch.setattr(
        module, "mark_confirmation_accepted", AsyncMock(side_effect=RuntimeError("PRIVATE"))
    )
    use_case = HandleWsChatMessageUseCase(jobs, object(), redis)
    kwargs = dict(
        thread_id="thread", msg={"confirm_offer_id": anchor.offer_id}, session={"user_id": owner}
    )
    with pytest.raises(RuntimeError):
        await use_case.execute(**kwargs)
    with pytest.raises(ConfirmationOfferError, match="confirmation_busy"):
        await use_case.execute(**kwargs)
    assert len(enqueue) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,kind",
    [
        ("watch_video", "tool"),
        ("deep_research", "mode"),
        ("image_gen", "mode"),
        ("expensive_run", "tool"),
    ],
)
@pytest.mark.parametrize("decision", ["accept", "decline"])
async def test_all_confirmation_choices_are_owned_idempotent_and_restore_original_context(
    mode, kind, decision
):
    from unittest.mock import AsyncMock

    redis = FakeRedis()
    owner = str(uuid4())
    anchor = await create_confirmation_offer(
        redis,
        thread_id="thread",
        user_id=owner,
        source_message_id=str(uuid4()),
        text="ORIGINAL_REQUEST",
        selected_model="GigaChat-2",
        route_override=None,
        resolved_category=None,
        input_type="text",
        attachments=[{"name": "input.md", "content": "PRIVATE"}],
        file_ids=["owned-file"],
        offer_mode=mode,
        offer_kind=kind,
        continuation={"file_context": "SERVER_CONTEXT"},
    )
    queued = []
    queue = SimpleNamespace(enqueue_agent_message=lambda **kw: queued.append(kw) or "task")
    jobs = SimpleNamespace(
        job_queue=queue,
        create_chat_job=AsyncMock(return_value=SimpleNamespace(job_id=uuid4())),
        update_job_celery_task_id=AsyncMock(),
    )
    use_case = HandleWsChatMessageUseCase(jobs, object(), redis)
    message = {
        "confirm_offer_id": anchor.offer_id,
        "confirmation_decision": decision,
        "text": "TAMPERED",
        "watch_video": True,
        "deep_research": True,
        "model": "OTHER",
    }
    first = await use_case.execute(thread_id="thread", msg=message, session={"user_id": owner})
    second = await use_case.execute(thread_id="thread", msg=message, session={"user_id": owner})
    assert len(queued) == 1
    assert first["job_id"] == second["job_id"]
    assert first["confirmation_status"] == ("accepted" if decision == "accept" else "declined")
    assert second["confirmation_status"] == first["confirmation_status"]
    call = queued[0]
    assert call["text"] == "ORIGINAL_REQUEST"
    assert call["selected_model"] == "GigaChat-2"
    assert call["attachments"][0]["content"] == "PRIVATE"
    assert call["file_context"] == "SERVER_CONTEXT"
    assert call["session_data"]["watch_video"] == (mode == "watch_video" and decision == "accept")
    assert call["session_data"]["confirmation_cancelled"] == (
        mode == "expensive_run" and decision == "decline"
    )
    assert "PRIVATE" not in repr(first)
    with pytest.raises(ConfirmationOfferError, match="confirmation_invalid"):
        await use_case.execute(
            thread_id="thread",
            msg={
                **message,
                "confirmation_decision": "decline" if decision == "accept" else "accept",
            },
            session={"user_id": owner},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("redis_type", [FakeRedis, SyncRedis])
async def test_confirmation_anchor_is_owner_bound_and_idempotent(redis_type) -> None:
    redis = redis_type()
    user_id = str(uuid4())
    anchor = await create_confirmation_offer(
        redis,
        thread_id="thread-1",
        user_id=user_id,
        source_message_id=str(uuid4()),
        text="Напиши статью по материалам",
        selected_model="GigaChat-2",
        route_override="pdf_gen",
        resolved_category="pdf_gen",
        input_type="text",
        attachments=[
            {
                "file_id": str(uuid4()),
                "name": "materials.md",
                "content": "PRIVATE_ATTACHMENT_MARKER",
            }
        ],
        file_ids=[],
    )

    claimed, duplicate = await claim_confirmation_offer(
        redis,
        anchor.offer_id,
        thread_id="thread-1",
        user_id=user_id,
    )
    assert duplicate is False
    accepted = await mark_confirmation_accepted(
        redis,
        claimed,
        job_id="job-1",
        celery_task_id="task-1",
    )
    replay, duplicate = await claim_confirmation_offer(
        redis,
        anchor.offer_id,
        thread_id="thread-1",
        user_id=user_id,
    )

    assert accepted.status == "accepted"
    assert UUID(accepted.source_message_id)
    assert duplicate is True
    assert replay.job_id == "job-1"
    with pytest.raises(ConfirmationOfferError) as forbidden:
        await claim_confirmation_offer(
            redis,
            anchor.offer_id,
            thread_id="thread-1",
            user_id=str(uuid4()),
        )
    assert forbidden.value.code == "confirmation_forbidden"


@pytest.mark.asyncio
@pytest.mark.parametrize("redis_type", [FakeRedis, SyncRedis])
async def test_ws_confirmation_restores_original_request_once(redis_type) -> None:
    redis = redis_type()
    user_id = str(uuid4())
    file_id = str(uuid4())
    anchor = await create_confirmation_offer(
        redis,
        thread_id="thread-1",
        user_id=user_id,
        source_message_id=str(uuid4()),
        text="Напиши статью по материалам",
        selected_model="GigaChat-2",
        route_override="pdf_gen",
        resolved_category="pdf_gen",
        input_type="text",
        attachments=[
            {
                "file_id": file_id,
                "name": "materials.md",
                "content": "SERVER_EXTRACTED_MATERIAL",
            }
        ],
        file_ids=[file_id],
    )

    class Queue:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def enqueue_agent_message(self, **kwargs):
            self.calls.append(kwargs)
            return "task-1"

    class Jobs:
        def __init__(self) -> None:
            self.job_queue = Queue()
            self.created = 0

        async def create_chat_job(self, **_kwargs):
            self.created += 1
            return SimpleNamespace(job_id=UUID("00000000-0000-0000-0000-000000000111"))

        async def update_job_celery_task_id(self, *_args):
            return None

    jobs = Jobs()
    use_case = HandleWsChatMessageUseCase(jobs, chat_service=object(), redis_client=redis)
    message = {"id": "client-message", "text": "", "confirm_offer_id": anchor.offer_id}
    session = {"user_id": user_id}

    first = await use_case.execute(thread_id="thread-1", msg=message, session=session)
    second = await use_case.execute(thread_id="thread-1", msg=message, session=session)

    assert first["type"] == "job_created"
    assert first["confirmation_status"] == "accepted"
    assert second["job_id"] == first["job_id"]
    assert second["confirmation_status"] == "accepted"
    assert jobs.created == 1
    assert len(jobs.job_queue.calls) == 1
    queued = jobs.job_queue.calls[0]
    assert queued["text"] == "Напиши статью по материалам"
    assert queued["selected_model"] == "GigaChat-2"
    assert queued["route_override"] == "pdf_gen"
    assert queued["attachments"][0]["content"] == "SERVER_EXTRACTED_MATERIAL"
    assert queued["session_data"]["file_ids"] == [file_id]
    assert queued["session_data"]["confirm_expensive_run"] is True


@pytest.mark.asyncio
async def test_ws_uses_shared_route_before_enqueuing_manual_document_request() -> None:
    calls: list[dict] = []

    class Queue:
        def enqueue_agent_message(self, **kwargs):
            calls.append(kwargs)
            return "task-document"

    class Jobs:
        job_queue = Queue()

        async def create_chat_job(self, **_kwargs):
            return SimpleNamespace(job_id=UUID("00000000-0000-0000-0000-000000000222"))

        async def update_job_celery_task_id(self, *_args):
            return None

    class Routing:
        async def resolve_route(self, **kwargs):
            assert kwargs["selected_model"] == "GigaChat-3-Lightning"
            return SimpleNamespace(
                selected_model="GigaChat-3-Lightning",
                route_override="pdf_gen",
                web_search=False,
                deep_research=False,
                routing_usage={},
                resolved_category=None,
            )

    use_case = HandleWsChatMessageUseCase(
        Jobs(),
        chat_service=SimpleNamespace(routing_service=Routing()),
    )
    await use_case.execute(
        thread_id="thread-document",
        msg={
            "id": "client-document",
            "text": "Напиши по прикрепленным материалам статью в PDF",
            "model": "GigaChat-3-Lightning",
            "input_type": "text",
            "attachments": [{"file_id": "owned-file", "name": "materials.md"}],
            "file_ids": ["owned-file"],
        },
        session={"user_id": "11111111-1111-1111-1111-111111111111"},
    )

    assert len(calls) == 1
    assert calls[0]["selected_model"] == "GigaChat-3-Lightning"
    assert calls[0]["route_override"] == "pdf_gen"
    assert calls[0]["attachments"] == [{"file_id": "owned-file", "name": "materials.md"}]
    assert calls[0]["session_data"]["file_ids"] == ["owned-file"]


@pytest.mark.asyncio
@pytest.mark.parametrize("redis_type", [FakeRedis, SyncRedis])
async def test_server_cached_attachment_text_wins_over_browser_payload(redis_type) -> None:
    redis = redis_type()
    user_id = str(uuid4())
    file_id = str(uuid4())
    digest = "b" * 64
    await cache_owner_attachment_evidence(
        redis,
        user_id=user_id,
        upload_result={
            "file_id": file_id,
            "content_sha256": digest,
            "filename": "materials.md",
            "mime_type": "text/markdown",
            "extracted_text": "SERVER_EXTRACTED_TEXT",
        },
    )

    class Repository:
        async def fetch_user_file_by_id(self, owner, requested_file_id):
            assert str(owner) == user_id
            assert str(requested_file_id) == file_id
            return SimpleNamespace(
                content_sha256=digest,
                original_name="materials.md",
            )

    files = SimpleNamespace(repository=Repository())
    result = await owner_checked_attachments(
        files,
        user_id=user_id,
        file_ids=[file_id],
        attachments=[
            {
                "file_id": file_id,
                "digest": digest,
                "name": "../../browser-name.md",
                "mime_type": "text/markdown",
                "content": "BROWSER_TAMPERED_TEXT",
                "source_url": "https://private.example/file",
                "storage_key": "secret/object/key",
            }
        ],
        redis=redis,
    )

    assert result == [
        {
            "kind": "document",
            "file_id": file_id,
            "name": "materials.md",
            "mime_type": "text/markdown",
            "digest": digest,
            "content": "SERVER_EXTRACTED_TEXT",
        }
    ]
    assert "BROWSER_TAMPERED_TEXT" not in repr(result)
    assert "source_url" not in repr(result)
    assert "storage_key" not in repr(result)


@pytest.mark.asyncio
async def test_browser_attachment_text_is_not_used_when_server_evidence_is_unavailable() -> None:
    user_id = str(uuid4())
    file_id = str(uuid4())
    digest = "e" * 64

    class Repository:
        async def fetch_user_file_by_id(self, _owner, _file_id):
            return SimpleNamespace(
                content_sha256=digest,
                original_name="materials.md",
                file_name="",
            )

    files = SimpleNamespace(repository=Repository())
    result = await owner_checked_attachments(
        files,
        user_id=user_id,
        file_ids=[file_id],
        attachments=[
            {
                "file_id": file_id,
                "digest": digest,
                "name": "materials.md",
                "content": "BROWSER_PRIVATE_MARKER",
            }
        ],
        redis=None,
    )

    assert result == [
        {
            "kind": "document",
            "file_id": file_id,
            "name": "materials.md",
            "mime_type": "text/markdown",
            "digest": digest,
            "content": "",
        }
    ]
    assert "BROWSER_PRIVATE_MARKER" not in repr(result)


def test_attachment_history_keeps_only_safe_durable_identity() -> None:
    file_id = str(uuid4())
    marker = "PRIVATE_ATTACHMENT_CONTENT"

    result = user_message_meta(
        [
            {
                "file_id": file_id,
                "name": "materials.md",
                "kind": "document",
                "mime_type": "text/markdown",
                "digest": "c" * 64,
                "content": marker,
                "source_url": "https://private.invalid/source",
            }
        ]
    )

    assert result == {
        "attachments": [
            {
                "filename": "materials.md",
                "file_type": "document",
                "file_id": file_id,
                "mime_type": "text/markdown",
                "digest": "c" * 64,
            }
        ]
    }
    assert marker not in repr(result)
    assert "source_url" not in repr(result)


@pytest.mark.asyncio
async def test_attachment_text_is_recovered_from_exact_library_file_after_cache_expiry(
    monkeypatch,
) -> None:
    user_id = str(uuid4())
    file_id = str(uuid4())
    digest = "d" * 64

    class Repository:
        async def fetch_user_file_by_id(self, _owner, _file_id):
            return SimpleNamespace(
                content_sha256=digest,
                original_name="materials.md",
                file_name="owned/materials.md",
            )

    class Files:
        repository = Repository()

        async def get_file_by_key(self, *, file_key):
            assert file_key == "owned/materials.md"
            return b"DURABLE_ATTACHMENT_TEXT"

    class Parser:
        async def parse(self, payload, key):
            assert payload == b"DURABLE_ATTACHMENT_TEXT"
            assert key == "owned/materials.md"
            return "DURABLE_ATTACHMENT_TEXT"

    monkeypatch.setattr(
        "service.services.chat.infrastructure.media.opendataloader_parser.OpenDataLoaderParser",
        Parser,
    )
    result = await owner_checked_attachments(
        Files(),
        user_id=user_id,
        file_ids=[file_id],
        attachments=[{"file_id": file_id, "digest": digest, "kind": "document"}],
        redis=None,
    )

    assert result[0]["content"] == "DURABLE_ATTACHMENT_TEXT"
    assert result[0]["file_id"] == file_id


def test_accepted_offer_never_expires_in_message_history() -> None:
    old = datetime.now(UTC) - timedelta(hours=1)
    metadata = {
        "mode_offer": {
            "mode": "expensive_run",
            "offer_id": "opaque-offer",
            "offered_at": old.isoformat(),
            "expires_in_sec": 30,
            "status": "accepted",
        }
    }

    result = expire_mode_offer(metadata)

    assert result["mode_offer"]["status"] == "accepted"
    assert "expired" not in result["mode_offer"]


def test_document_terminal_metadata_persists_only_closed_values() -> None:
    safe = persistable_meta(
        {
            "requested_authoring_model": "GigaChat-2",
            "actual_authoring_model": "GigaChat-2",
            "document_outcome": "draft_ready",
            "document_failure_code": "evidence_incomplete",
            "execution_status": "partial",
            "document_project_saved": True,
        },
        None,
    )
    assert safe["requested_authoring_model"] == "GigaChat-2"
    assert safe["actual_authoring_model"] == "GigaChat-2"
    assert safe["document_failure_code"] == "evidence_incomplete"
    assert safe["document_project_saved"] is True

    redacted = persistable_meta(
        {
            "requested_authoring_model": "private marker with spaces",
            "actual_authoring_model": "https://secret.invalid/model?token=private",
            "document_outcome": "private-outcome",
            "document_failure_code": "private-failure",
            "execution_status": "private-status",
        },
        None,
    )
    assert not redacted


def test_backend_stream_boundary_redacts_legacy_document_status() -> None:
    marker = "S36_PRIVATE_PROVIDER_BODY"
    payload = EventSerializer().serialize(
        event=SimpleNamespace(
            type=EventType.STATUS_UPDATE,
            agent_name="pdf_gen",
            data="safe",
            seq=1,
            metadata={
                "kind": "document_status",
                "document_status": {
                    "stage": "section_authoring",
                    "status": "failed",
                    "failure_code": "draft_protocol",
                    "retryable": False,
                    "raw_response": marker,
                },
                "arguments": marker,
            },
        ),
        job_id="job",
    )

    assert payload["metadata"] == {
        "kind": "document_status",
        "document_status": {
            "stage": "section_authoring",
            "status": "failed",
            "retryable": False,
            "failure_code": "draft_protocol",
        },
        "document_failure_code": "draft_protocol",
    }
    assert marker not in repr(payload)


@pytest.mark.asyncio
async def test_expensive_confirmation_storage_failure_is_fail_closed(monkeypatch) -> None:
    class Billing:
        def __init__(self, *_args, **_kwargs):
            pass

        async def has_sufficient_credits(self, _user_id):
            return True

        async def reserve(self, *_args, **_kwargs):
            raise AssertionError("must not reserve before confirmation")

    monkeypatch.setattr(
        "service.services.billing.application.billing_service.BillingService",
        Billing,
    )
    monkeypatch.setattr(
        "service.services.billing.persistence.billing_repository.BillingRepository",
        lambda *_args, **_kwargs: None,
    )

    async def estimate(**_kwargs):
        return 5_001

    async def emit(**_kwargs):
        raise ConfirmationOfferError("confirmation_unavailable")

    with pytest.raises(ConfirmationOfferError) as unavailable:
        await reservation.reserve_credits_or_short_circuit(
            pg_connector=None,
            config=None,
            publisher=object(),
            job_repo=None,
            session=None,
            job_id="job",
            thread_id="thread",
            text="expensive",
            user_id=str(uuid4()),
            selected_model="GigaChat-2",
            context_chars=0,
            attachments=[],
            expensive_run_confirmed=False,
            redis_client=None,
            confirmation_context={},
            overlay_billing=lambda *_args: SimpleNamespace(
                expensive_run_confirmation_credits=5_000
            ),
            estimate_credits=estimate,
            emit_expensive=emit,
            emit_insufficient=emit,
        )
    assert unavailable.value.code == "confirmation_unavailable"


@pytest.mark.asyncio
async def test_confirmation_is_not_published_when_source_turn_is_not_persisted() -> None:
    redis = FakeRedis()

    class Publisher:
        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def publish_payload(self, payload: dict) -> None:
            self.payloads.append(payload)

    publisher = Publisher()
    persisted_ids: list[tuple[str, str]] = []

    async def persist_turn(**kwargs):
        persisted_ids.append((kwargs["user_message_id"], kwargs["assistant_message_id"]))
        return False

    async def update_status(*_args, **_kwargs):
        raise AssertionError("an unpersisted offer must not update job status")

    with pytest.raises(ConfirmationOfferError) as unavailable:
        await reservation.emit_expensive_confirmation(
            publisher=publisher,
            job_repo=None,
            session=None,
            job_id="job",
            thread_id="thread",
            text="expensive request",
            user_id=str(uuid4()),
            selected_model="GigaChat-2",
            estimated_credits=5_001,
            attachments=[],
            redis_client=redis,
            confirmation_context={},
            persist_turn=persist_turn,
            update_job_status=update_status,
        )

    assert unavailable.value.code == "confirmation_unavailable"
    assert len(persisted_ids) == 1
    assert all(UUID(message_id) for message_id in persisted_ids[0])
    assert publisher.payloads == []
    assert redis.values == {}
