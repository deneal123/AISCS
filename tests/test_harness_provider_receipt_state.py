"""Receipt восстанавливает меняющийся provider state без повторного inference."""

from unittest.mock import AsyncMock

import pytest

from service.domain.client.calls.harness_state import restore_state
from service.domain.client.calls.harness_stream import paid_stream
from service.domain.client.calls.harness_transport import paid_chat
from service.domain.client.protocol import ProviderRoundState
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.shared.harness_protocol import HarnessFailure, ProviderBinding
from tests.test_harness_reconciliation import Journal
from tests.test_harness_runtime import response


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("state_id", ["PRIVATE_NEW_STATE", None])
async def test_receipt_restores_response_state_after_crash_before_checkpoint(streaming, state_id):
    journal = Journal(None)
    sends = []

    async def invoke(execution, *, replay):
        execution.harness = journal.client()
        session = execution.provider_session
        session.set_private_state("gigachat", "PRIVATE_OLD_CHECKPOINT_STATE")

        def received():
            assert not replay, "provider_must_not_be_replayed"
            sends.append(1)
            session.clear_private_state("gigachat")
            if state_id is not None:
                session.set_private_state("gigachat", state_id)

        async def chat():
            received()
            return response()

        async def stream(operation_id):
            received()
            yield "done"

        if streaming:
            parts = [
                part
                async for part in paid_stream(
                    stream,
                    provider="gigachat",
                    model="test",
                    messages=[],
                    parameters={
                        "provider_session": session,
                        "round_state": ProviderRoundState(
                            prompt=10, completion=2, total=12, finish_reason="stop"
                        ),
                        "max_tokens": 100,
                    },
                )
            ]
            assert parts == ["done"]
        else:
            result, _ = await paid_chat(
                chat, provider="gigachat", model="test", payload={"max_tokens": 100}
            )
            assert result.choices[0].message.content == "done"
        assert session.private_state("gigachat") == state_id

    with use_run_execution(PrivateRunResources()) as execution:
        await invoke(execution, replay=False)
    stored = next(iter(journal.operations.values()))["receipt"]
    assert ProviderBinding.model_validate(stored["provider_state"]).model_dump() == {
        "provider": "gigachat",
        "model": "test",
        "state_id": state_id,
    }
    assert journal.counts["checkpoint"] == 0
    with use_run_execution(PrivateRunResources()) as resumed:
        await invoke(resumed, replay=True)
    assert len(sends) == journal.counts["dispatch"] == journal.counts["call_receipt"] == 1


@pytest.mark.parametrize(
    "binding",
    [
        None,
        {"provider": "openai", "model": "test", "state_id": "PRIVATE_STATE"},
        {"provider": "gigachat", "model": "different", "state_id": "PRIVATE_STATE"},
        {"provider": "gigachat", "model": "test", "state_id": 12},
    ],
)
def test_legacy_or_incompatible_tool_response_never_reuses_stale_state(binding):
    session = AsyncMock()
    receipt = {"message": {"tool_calls": [{"id": "call"}]}, "provider_state": binding}
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        restore_state(session, receipt, provider="gigachat", model="test")
    session.clear_private_state.assert_not_called()
    session.set_private_state.assert_not_called()


def test_legacy_stateless_provider_receipt_remains_readable():
    restore_state(None, {"message": {"tool_calls": []}}, provider="openai", model="test")


def test_private_state_is_excluded_from_receipt_repr():
    from uuid import uuid4

    from service.shared.harness_protocol import CallReceipt

    receipt = CallReceipt(
        operation_id=str(uuid4()),
        status="succeeded",
        provider_state=ProviderBinding(
            provider="gigachat", model="test", state_id="PRIVATE_PROVIDER_STATE"
        ),
    )
    assert "PRIVATE_PROVIDER_STATE" not in repr(receipt)
    assert "PRIVATE_PROVIDER_STATE" not in repr(receipt.provider_state)


@pytest.mark.asyncio
async def test_checkpoint_json_omission_does_not_allocate_another_paid_call():
    journal = Journal(None)
    send = AsyncMock(return_value=response())
    first = [{"role": "user", "content": "Создай файл"}, {"role": "assistant", "content": None}]
    restored = [{"role": "user", "content": "Создай файл"}, {"role": "assistant"}]
    for messages in (first, restored):
        with use_run_execution(PrivateRunResources()) as execution:
            execution.harness = journal.client()
            await paid_chat(send, provider="gigachat", model="test", payload={"messages": messages})
    assert send.await_count == journal.counts["dispatch"] == 1


@pytest.mark.asyncio
async def test_legacy_checkpoint_cannot_silently_adopt_new_request_digest_codec():
    from service.shared.harness_protocol import Continuation

    journal = Journal(None)
    journal.current = journal.current.model_copy(
        update={
            "continuation": Continuation(
                messages=[{"role": "user", "content": "Прежний запрос"}], phase="model"
            ),
        }
    )
    send = AsyncMock(return_value=response())
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = journal.client()
        with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
            await paid_chat(send, provider="gigachat", model="test", payload={"messages": []})
        with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
            await execution.harness.checkpoint(execution, [], phase="model")
    send.assert_not_awaited()
    assert (
        journal.counts["grant"] == journal.counts["dispatch"] == journal.counts["checkpoint"] == 0
    )
