import pytest

from service.services.chat.domain.chat_exceptions import JobExecutionError
from service.services.chat.domain.chat_job_orchestrator import ChatJobOrchestrator


class _Handler:
    def __init__(self, payload):
        self.payload = payload

    async def dispatch_and_wait(self, command, timeout_sec=30.0):
        if self.payload.get("status") == "failed":
            raise JobExecutionError(self.payload.get("error") or "x")
        return self.payload["result"]


@pytest.mark.asyncio
async def test_execute_success() -> None:
    from service.services.chat.domain.chat_contracts import ChatProcessingMetadata, ChatReplyResult

    handler = _Handler(
        {
            "status": "success",
            "result": ChatReplyResult(
                reply="ok",
                thread_id="t1",
                file_url="u",
                metadata=ChatProcessingMetadata(data={"a": 1}),
            ),
        }
    )
    orchestrator = ChatJobOrchestrator(handler=handler)
    result = await orchestrator.execute("t1", "hello", None, None, None, False, False, "", None)
    assert result.reply == "ok"
    assert result.thread_id == "t1"
    assert result.file_url == "u"
    assert result.metadata["a"] == 1


@pytest.mark.asyncio
async def test_execute_failed_status_raises() -> None:
    orchestrator = ChatJobOrchestrator(handler=_Handler({"status": "failed", "error": "x"}))
    with pytest.raises(JobExecutionError):
        await orchestrator.execute("t1", "hello", None, None, None, False, False, "", None)


# ── A2 (аудит): usage роутера едет в воркер через session_data ────────────────


class _CapturingHandler:
    def __init__(self) -> None:
        self.command = None

    async def dispatch_and_wait(self, command, timeout_sec=30.0):
        from service.services.chat.domain.chat_contracts import ChatReplyResult

        self.command = command
        return ChatReplyResult(reply="ok", thread_id=command.thread_id)


async def _session_data_for(routing_usage):
    handler = _CapturingHandler()
    orchestrator = ChatJobOrchestrator(handler=handler)
    await orchestrator.execute(
        "t1",
        "q",
        "u1",
        None,
        None,
        False,
        False,
        "",
        None,
        routing_usage=routing_usage,
    )
    return handler.command.session_data


@pytest.mark.asyncio
async def test_router_usage_stashed_in_session_data() -> None:
    sd = await _session_data_for(
        {"prompt": 100, "completion": 20, "total": 120, "model": "router-m"}
    )
    assert sd["session_id"] == "t1"
    assert sd["_router_usage"]["total"] == 120
    assert sd["_router_usage"]["model"] == "router-m"


@pytest.mark.asyncio
async def test_empty_router_usage_not_stashed() -> None:
    # Ручной режим/regex → usage пуст: ключ не добавляем (воркеру нечего тарифить).
    assert await _session_data_for({}) == {"session_id": "t1"}
    assert await _session_data_for(None) == {"session_id": "t1"}
