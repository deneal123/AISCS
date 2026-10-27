"""Owner-checked, generation-pinned commands with fail-closed at-most-once admission.

Redis stores a command digest, never command text. Output expires with the runtime.
A lost dispatch/result acknowledgement is not permission to execute again.
"""

import asyncio
import hashlib
import json
import math
import time

from service.infrastructure.workspace_client import _redis_call
from service.services.chat.application.ide.edits import IdeEditService
from service.services.chat.application.workspace_collaboration import verify_capability
from service.services.chat.domain.ide.console import CommandReceipt, CommandResult, ConsoleError


class IdeConsoleService:
    def __init__(self, runtime, redis):
        self.runtime, self.redis = runtime, redis
        self.edits = IdeEditService(runtime, redis)

    def agent_entry(self, saved, infra):
        from service.services.chat.application.ide.commands.service import AgentConsole

        return AgentConsole(self, saved, infra)

    def _key(self, scope, execution_id):
        identity = f"{scope.user_id}/{scope.thread_id}/{scope.repository_id}/{execution_id}"
        return "ide:console:" + hashlib.sha256(identity.encode()).hexdigest()

    async def _read(self, key):
        try:
            raw = await _redis_call(self.redis, "get", key)
            if raw is None:
                return None
            value = json.loads(raw)
            if type(value) is not dict or set(value) != {"digest", "receipt"}:
                raise ValueError
            CommandReceipt.model_validate(value["receipt"])
            return value
        except Exception:
            raise ConsoleError() from None

    async def status(self, scope, execution_id):
        await self.runtime._check_owner(scope)
        value = await self._read(self._key(scope, execution_id))
        if value is None:
            raise ConsoleError("ide_console_status_unknown")
        return value["receipt"]

    async def execute(self, scope, payload, session):
        await self.runtime._check_owner(scope)
        key = self._key(scope, payload.execution_id)
        digest = hashlib.sha256(f"{payload.generation}\0{payload.command}".encode()).hexdigest()
        previous = await self._read(key)
        if previous is not None:
            return self._replay(previous, digest)
        resolved, capability, store = await self.edits._context(scope, payload.generation, session)
        await store.preflight(verify_capability(capability), mutation="exec")
        await self.edits._current(scope, resolved)
        remaining = math.ceil(resolved.binding.expires_at - time.time())
        if remaining < 1:
            raise ConsoleError("ide_console_status_unknown")
        receipt = CommandReceipt(
            execution_id=payload.execution_id,
            repository_id=scope.repository_id,
            generation=payload.generation,
            state="dispatching",
        ).model_dump(mode="json")
        value = {"digest": digest, "receipt": receipt}
        try:
            claimed = await _redis_call(
                self.redis, "set", key, json.dumps(value), nx=True, ex=remaining
            )
        except Exception:
            # No remote execution follows a lost admission ACK.
            raise ConsoleError("ide_console_status_unknown") from None
        if not claimed:
            previous = await self._read(key)
            if previous is None:
                raise ConsoleError("ide_console_status_unknown")
            return self._replay(previous, digest)
        try:
            result = await self.runtime.client.execute(
                scope.user_id, resolved.binding, command=payload.command, capability=capability
            )
            receipt.update(
                state="completed", result=CommandResult.model_validate(result).model_dump()
            )
        except asyncio.CancelledError:
            # Claim remains dispatching: reconnect observes, never reruns the command.
            raise
        except Exception:
            receipt.update(state="unknown")
        value["receipt"] = receipt
        try:
            remaining = math.ceil(resolved.binding.expires_at - time.time())
            if remaining > 0:
                await _redis_call(self.redis, "set", key, json.dumps(value), xx=True, ex=remaining)
        except Exception:
            # A received output is still factual even if journal publication failed.
            pass
        return receipt

    @staticmethod
    def _replay(value, digest):
        if value["digest"] != digest:
            raise ConsoleError("ide_console_intent_conflict")
        return value["receipt"]
