"""A publication may project only into its owner's original assistant thread."""

import json
import uuid

import pytest

from service.services.chat.application.documents.publication.service import _attach_generated_file
from service.services.chat.persistence.documents.publication import enqueue


class Result:
    def __init__(self, message):
        self.message = message

    def mappings(self):
        return self

    def first(self):
        return self.message

    def scalar_one_or_none(self):
        return self.message["id"] if self.message else None


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["owner", "thread", "sender", None])
async def test_attach_checks_owner_thread_and_assistant_before_metadata_write(mismatch):
    owner = uuid.uuid4()
    thread = uuid.uuid4()
    row = {
        "user_id": uuid.uuid4() if mismatch == "owner" else owner,
        "thread_id": str(uuid.uuid4() if mismatch == "thread" else thread),
        "assistant_message_id": 7,
        "role": "pdf",
        "filename": "owned.pdf",
        "mime_type": "application/pdf",
    }
    writes = []

    class Session:
        async def execute(self, query, values):
            sql = str(query)
            if sql.lstrip().startswith("SELECT"):
                guarded = (
                    "t.user_id=:user_id" in sql
                    and "t.thread_id=:thread_id" in sql
                    and "m.sender IN ('assistant', 'agent')" in sql
                )
                allowed = (
                    values.get("user_id") == owner
                    and values.get("thread_id") == str(thread)
                    and mismatch != "sender"
                )
                if guarded and not allowed:
                    return Result(None)
                if mismatch is None:
                    assert "FOR UPDATE OF m" in sql
                return Result({"id": 7, "metadata": {"model": "author-model"}})
            writes.append(json.loads(values["metadata"]))
            return Result(None)

    await _attach_generated_file(Session(), row, uuid.uuid4())
    assert bool(writes) == (mismatch is None)
    if writes:
        assert writes[0]["model"] == "author-model"


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [False, True])
async def test_enqueue_does_not_bind_latest_assistant_from_foreign_thread(owned):
    owner, supplied = uuid.uuid4(), uuid.uuid4()
    inserts = []

    class Session:
        async def execute(self, query, values):
            if str(query).lstrip().startswith("SELECT"):
                guarded = "t.user_id=:user_id" in str(query)
                return Result({"id": 7} if not guarded or values.get("user_id") == owner else None)
            inserts.append(values)
            return Result({"id": uuid.uuid4(), "status": "pending_delivery"})

    await enqueue(
        Session(),
        user_id=owner if owned else supplied,
        thread_id=str(uuid.uuid4()),
        workspace_id="opaque-workspace",
        billing_job_id="opaque-billing",
        descriptors=({},),
    )
    assert inserts[0]["assistant_message_id"] == (7 if owned else None)


@pytest.mark.asyncio
async def test_explicit_origin_never_uses_newer_assistant_message():
    origin = uuid.uuid4()
    inserts = []

    class Session:
        async def execute(self, query, values):
            if str(query).lstrip().startswith("SELECT"):
                assert "m.message_id=:origin_message_id" in str(query)
                assert "ORDER BY m.id DESC" not in str(query)
                assert values["origin_message_id"] == origin
                return Result({"id": 7})
            inserts.append(values)
            return Result({"id": uuid.uuid4(), "status": "pending_delivery"})

    await enqueue(
        Session(),
        user_id=uuid.uuid4(),
        thread_id=str(uuid.uuid4()),
        workspace_id="opaque-workspace",
        billing_job_id="opaque-billing",
        descriptors=({},),
        origin_message_id=str(origin),
    )
    assert inserts[0]["assistant_message_id"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, True])
async def test_explicit_missing_or_invalid_origin_never_falls_back_to_latest(invalid):
    calls = []

    class Session:
        async def execute(self, query, values):
            calls.append(str(query))
            return Result(None)

    origin = "private-invalid-origin" if invalid else str(uuid.uuid4())
    with pytest.raises(ValueError) as failure:
        await enqueue(
            Session(),
            user_id=uuid.uuid4(),
            thread_id=str(uuid.uuid4()),
            workspace_id="opaque-workspace",
            billing_job_id="opaque-billing",
            descriptors=({},),
            origin_message_id=origin,
        )
    assert str(failure.value) == (
        "publication_message_invalid" if invalid else "publication_message_missing"
    )
    assert not any("INSERT" in query for query in calls)
    assert not invalid or not calls
