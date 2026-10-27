"""Run-private acknowledged backend client. No transparent retries or model URLs."""

import asyncio
import json
import time
from uuid import UUID, uuid5

from service.infrastructure.harness.exchange import post_exchange
from service.infrastructure.harness.reconciliation import reconcile_exchange
from service.shared.harness_protocol import (
    CallReceipt,
    Continuation,
    Exchange,
    HarnessFailure,
    PaidCall,
    Snapshot,
)
from service.shared.task_contract import TaskState, digest_payload


class HarnessClient:
    async def command(self, *, action, operation_id, spec=None):
        from service.infrastructure.harness.commands import post_command

        payload = {"version": 1, "action": action, "operation_id": operation_id}
        if spec is not None:
            payload["spec"] = spec
        result = await post_command(
            self.url.removesuffix("/exchange") + "/commands",
            self._capability,
            payload,
            transport=self.transport,
        )
        self.current = Snapshot.model_validate(result["snapshot"])
        if self.current.admission.task_id != self.task_id:
            raise HarnessFailure("harness_fenced")
        return result["command"]

    def __init__(self, reference, *, transport=None):
        from service.settings import config

        self._capability = reference["capability"]
        self.task_id = str(UUID(reference["task_id"]))
        self.url = config.agents.harness_backend_url.rstrip("/") + "/internal/harness/v1/exchange"
        self.transport = transport
        self.current: Snapshot | None = None
        self.failure = ""
        self._lock = asyncio.Lock()
        self.effect_lock = asyncio.Lock()
        self._active_checkpoint = time.monotonic()

    async def _send(self, **values):
        return await post_exchange(
            self.url, self._capability, Exchange.model_validate(values), transport=self.transport
        )

    async def exchange(self, **values):
        payload = Exchange.model_validate(values)
        try:
            try:
                result = await self._send(**values)
            except HarnessFailure as error:
                if error.code != "checkpoint_unavailable":
                    raise
                result = await reconcile_exchange(payload, self.current, self._send)
                if result is None:
                    raise error
            if "snapshot" in result:
                self.current = Snapshot.model_validate(result["snapshot"])
                if self.current.admission.task_id != self.task_id:
                    raise HarnessFailure("harness_fenced")
            return result
        except HarnessFailure as error:
            self.failure = error.code
            raise
        except (ValueError, KeyError, TypeError):
            self.failure = "checkpoint_unavailable"
            raise HarnessFailure() from None

    async def load(self):
        await self.exchange(opcode="state")
        if self.current.stopped:
            self.failure = "cancelled"
            raise HarnessFailure("cancelled")
        return self.current

    async def checkpoint(
        self,
        execution,
        messages,
        *,
        phase,
        advance=False,
        agent_name=None,
        length_continuations=None,
        refinement=None,
    ):
        from .call_payload import require_replay_codec

        async with self._lock:
            current = await self.load()
            require_replay_codec(current.continuation)
            state = execution.task_state
            if state is None:
                self.failure = "task_contract_invalid"
                raise HarnessFailure(self.failure)
            raw = state.model_dump(mode="json")
            raw["budget"] = current.state.budget.model_dump(mode="json")
            measured_at = time.monotonic()
            elapsed = int((measured_at - self._active_checkpoint) * 1000)
            raw["budget"]["active_ms"] += elapsed
            state = TaskState.model_validate(raw)
            provider = execution.provider_session
            binding = None
            if provider.pinned_provider:
                binding = {
                    "provider": provider.pinned_provider,
                    "model": provider.pinned_model,
                    "state_id": provider.private_state(provider.pinned_provider),
                }
            continuation = Continuation.model_validate(
                {
                    "messages": messages,
                    "refinement": refinement or current.continuation.refinement,
                    "provider": binding,
                    "agent_name": agent_name or current.continuation.agent_name,
                    "next_step": current.continuation.next_step + int(advance),
                    "length_continuations": (
                        current.continuation.length_continuations
                        if length_continuations is None
                        else length_continuations
                    ),
                    "call_payload_version": 2,
                    "phase": phase,
                    "clarification": current.continuation.clarification,
                }
            )
            await self.exchange(
                opcode="checkpoint",
                expected_revision=current.revision,
                continuation=continuation,
                state=state,
            )
            execution.task_state = self.current.state
            # The persisted value is measured before HTTP/ACK reconciliation.
            # Charge that latency at the next boundary, not discard it here.
            self._active_checkpoint = measured_at

    async def before_call(self, provider, model, payload, *, kind="chat", purpose=None):
        if self.failure:
            raise HarnessFailure(self.failure)
        from service.domain.execution.context import current_execution

        execution = current_execution()
        binding = execution.provider_session if execution is not None else None
        if (
            (kind == "chat" or purpose is not None)
            and binding
            and binding.pinned_provider
            and (provider != binding.pinned_provider or model != binding.pinned_model)
        ):
            self.failure = "provider_state_incompatible"
            raise HarnessFailure(self.failure)
        from .call_payload import canonical_call_payload, require_replay_codec

        require_replay_codec(self.current.continuation)
        clean = canonical_call_payload(payload)
        # Binary/media payloads need their own bounded adapter; never stringify objects/keys.
        encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        request_digest = digest_payload(clean)
        step = self.current.continuation.next_step
        if purpose is not None and (purpose != "instruction_refinement" or kind != "meta_usage"):
            raise HarnessFailure("provider_state_incompatible")
        identity = (
            f"provider-purpose:{purpose}"
            if purpose is not None
            else f"provider:{step}:{provider}:{model}:{request_digest}"
        )
        operation_id = str(uuid5(UUID(self.task_id), identity))
        limit = self.current.admission
        active = (
            self.current.state.budget.active_ms
            if self.current.state
            else self.current.continuation.admission_active_ms
        )
        if (
            active + int((time.monotonic() - self._active_checkpoint) * 1000)
            >= limit.active_limit_ms
        ):
            self.failure = "budget_exhausted"
            raise HarnessFailure(self.failure)
        completion = (
            clean.get("max_tokens") or clean.get("max_completion_tokens") or limit.completion_limit
        )
        call = PaidCall(
            operation_id=operation_id,
            provider=provider,
            model=model,
            prompt=len(encoded.encode()) + 1024,
            completion=completion,
            request_digest=request_digest,
            kind=kind,
            continuation_step=step if kind == "chat" else None,
            canonical_request=encoded,
        )
        result = await self.exchange(opcode="grant", call=call)
        operation = result["operation"]
        if operation["status"] == "succeeded":
            from .call_payload import replay_receipt

            return replay_receipt(operation_id, operation)
        if operation["status"] != "allocated":
            self.failure = "operation_unknown"
            raise HarnessFailure(self.failure)
        result = await self.exchange(opcode="dispatch", operation_id=operation_id)
        if result["operation"].get("dispatch_allowed") is not True:
            self.failure = "operation_unknown"
            raise HarnessFailure(self.failure)
        return operation_id, None

    async def complete_call(
        self, operation_id, *, usage=None, message=None, provider_state=None, finish_reason=None
    ):
        usage = usage or {}
        prompt = int(usage.get("prompt_tokens", usage.get("prompt", 0)) or 0)
        completion = int(usage.get("completion_tokens", usage.get("completion", 0)) or 0)
        unknown = not (prompt or completion) or bool(usage.get("estimated"))
        receipt = CallReceipt(
            operation_id=operation_id,
            status="unknown" if unknown else "succeeded",
            prompt=prompt,
            completion=completion,
            estimated=bool(usage.get("estimated")),
            message=message,
            finish_reason=finish_reason,
            provider_state=provider_state,
        )
        result = await self.exchange(opcode="call_receipt", receipt=receipt)
        if result["operation"]["status"] == "unknown":
            self.failure = "cost_unknown"
        elif message is not None and finish_reason is None:
            # Стоимость подтверждена, но отсутствие terminal нельзя объявлять stop.
            self.failure = "provider_state_incompatible"

    async def fail_call(self, operation_id):
        try:
            await self.complete_call(operation_id)
        finally:
            self.failure = self.failure or "operation_unknown"
