import threading
import uuid

import pytest

from service.services.chat.domain.process_chat_message_handler import (
    ProcessChatMessageCommand,
    ProcessChatMessageHandler,
)


def test_normalize_result_payload_adds_selected_model_and_keeps_reply_format() -> None:
    result = {
        "status": "success",
        "reply": "Hello",
        "metadata": {"source": "worker"},
        "file_url": None,
    }

    normalized = ProcessChatMessageHandler.normalize_result_payload(
        result,
        thread_id="thread-1",
        selected_model="mws-gpt-alpha",
    )

    assert normalized.reply == "Hello"
    assert normalized.thread_id == "thread-1"
    assert normalized.metadata.data == {
        "source": "worker",
        "selected_model": "mws-gpt-alpha",
    }


def test_normalize_result_payload_marks_provider_unavailable_for_empty_reply() -> None:
    result = {
        "status": "success",
        "reply": "",
        "metadata": {"provider_error": "timeout"},
    }

    normalized = ProcessChatMessageHandler.normalize_result_payload(
        result,
        thread_id="thread-2",
        selected_model=None,
    )

    assert normalized.reply
    assert normalized.metadata["provider_unavailable"] is True
    assert normalized.metadata["provider_error"] == "timeout"


@pytest.mark.asyncio
async def test_dispatch_and_wait_offloads_blocking_get_to_thread() -> None:
    # Блокирующий AsyncResult.get() должен выполняться в ОТДЕЛЬНОМ треде, а не в
    # event loop — иначе он замораживает весь loop на timeout_sec.
    main_thread = threading.current_thread()
    seen: dict = {}

    class _JobResp:
        job_id = uuid.uuid4()

    class _JobService:
        async def create_chat_job(self, *, user_id, thread_id, text):
            return _JobResp()

    class _Handle:
        def get(self, timeout):
            seen["thread"] = threading.current_thread()
            seen["timeout"] = timeout
            return {"status": "success", "reply": "Hi", "metadata": {"source": "worker"}}

    class _JobQueue:
        def enqueue_process_agent_message(self, **kwargs):
            return _Handle()

    handler = ProcessChatMessageHandler(job_service=_JobService(), job_queue=_JobQueue())
    cmd = ProcessChatMessageCommand(thread_id="t1", user_id=1, text="hello")

    result = await handler.dispatch_and_wait(cmd, timeout_sec=5.0)

    assert result.reply == "Hi"
    assert result.thread_id == "t1"
    assert seen["timeout"] == 5.0
    assert seen["thread"] is not main_thread  # get() выполнен вне event-loop-треда
