"""Concurrent artifact deliveries must preserve one assistant's file projection."""

import asyncio
import copy
import json
import uuid

import pytest

from service.services.chat.application.documents.publication.service import _attach_generated_file


class _Result:
    def __init__(self, metadata):
        self.metadata = metadata

    def mappings(self):
        return self

    def first(self):
        return {"id": 7, "metadata": self.metadata}


@pytest.mark.asyncio
@pytest.mark.parametrize("first_role", ["pdf", "source_bundle"])
async def test_concurrent_pdf_and_source_delivery_merge_without_lost_update(first_role):
    original = {"model": "author-model", "document_outcome": "deferred", "keep": {"a": 1}}
    stored = copy.deepcopy(original)
    lock = asyncio.Lock()
    both_read = asyncio.Event()
    read_count = 0

    class Session:
        def __init__(self):
            self.locked = False

        async def execute(self, query, values):
            nonlocal stored, read_count
            if str(query).startswith("SELECT"):
                self.locked = "FOR UPDATE" in str(query)
                if self.locked:
                    await lock.acquire()
                snapshot = copy.deepcopy(stored)
                read_count += 1
                if read_count == 2:
                    both_read.set()
                if not self.locked:
                    await both_read.wait()
                return _Result(snapshot)
            stored = json.loads(values["metadata"])
            return None

        async def commit(self):
            if self.locked:
                self.locked = False
                lock.release()

    pdf, bundle = uuid.uuid4(), uuid.uuid4()
    owner, thread = uuid.uuid4(), str(uuid.uuid4())

    async def deliver(role, file_id):
        session = Session()
        await _attach_generated_file(
            session,
            {
                "assistant_message_id": 7,
                "user_id": owner,
                "thread_id": thread,
                "role": role,
                "filename": "document.pdf" if role == "pdf" else "source.zip",
                "mime_type": "application/pdf" if role == "pdf" else "application/zip",
            },
            file_id,
        )
        await session.commit()

    async with asyncio.timeout(2):
        calls = [deliver("pdf", pdf), deliver("source_bundle", bundle)]
        if first_role == "source_bundle":
            calls.reverse()
        await asyncio.gather(*calls)
    assert {entry["file_id"] for entry in stored["generated_files"]} == {str(pdf), str(bundle)}
    assert stored["document_outcome"] == stored["execution_status"] == "completed"
    assert stored["model"] == original["model"]
    assert stored["keep"] == original["keep"]
    await deliver("source_bundle", bundle)
    assert len(stored["generated_files"]) == 2
