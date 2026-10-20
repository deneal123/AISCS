"""Private addressable sessions; Engine/journal identities survive this cache."""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from drivers.base import DriverError
from drivers.commands.engine import Engine


@dataclass
class CommandSession:
    stream: object
    identity: dict
    sent: bool = False
    result: asyncio.Task | None = None


class DockerCommands:
    def __init__(self):
        self.engine = Engine()
        self.sessions = {}

    async def create(self, ref, operation_id):
        operation = str(UUID(str(operation_id)))
        return await self.engine.create(ref.container_id, operation)

    async def ready(self, ref, operation_id, exec_id):
        await self.engine.inspect(exec_id, ref.container_id)
        if exec_id in self.sessions:
            return self.sessions[exec_id].identity
        stream = await self.engine.start(exec_id)
        try:
            data = await stream.message()
            if (
                data.get("type") != "ready"
                or type(data.get("version")) is not int
                or data.get("version") != 1
                or data.get("operation_id") != str(operation_id)
                or type(data.get("pid")) is not int
                or data["pid"] <= 1
                or not isinstance(data.get("start_time"), str)
                or not data["start_time"].isdigit()
            ):
                raise DriverError("command_handshake_invalid")
            self.sessions[exec_id] = CommandSession(stream, data)
            return data
        except BaseException:
            await stream.close()
            raise

    async def dispatch(
        self,
        ref,
        operation_id,
        exec_id,
        *,
        argv,
        timeout_sec,
        output_limit,
        verification_profile=None,
        verification_target=None,
    ):
        data = await self.engine.inspect(exec_id, ref.container_id)
        session = self.sessions.get(exec_id)
        if (
            session is None
            or session.sent
            or not data.get("Running")
            or session.identity.get("operation_id") != str(operation_id)
        ):
            raise DriverError("command_dispatch_unknown")
        # Mark before touching the stream: a lost drain ACK never permits resend.
        session.sent = True
        try:
            await session.stream.send(
                {
                    "version": 1,
                    "action": "run",
                    "operation_id": str(operation_id),
                    "argv": argv,
                    "timeout_sec": timeout_sec,
                    "output_limit": output_limit,
                    "verification_profile": verification_profile,
                    "verification_target": verification_target,
                }
            )
        finally:
            session.result = asyncio.create_task(self._collect(session, timeout_sec))

    @staticmethod
    async def _collect(session, timeout):
        try:
            data = await session.stream.message(timeout=timeout + 15)
            if data.get("type") != "done" or data.get("version") != 1:
                return None
            return data
        except (Exception, asyncio.CancelledError):
            return None
        finally:
            await session.stream.close()

    async def status(
        self, ref, operation_id, exec_id, *, supervisor=None, user_start_disallowed=False
    ):
        data = await self.engine.inspect(exec_id, ref.container_id)
        config = data.get("ProcessConfig", {})
        expected = ["-I", "-S", "/opt/gpthub-harness/supervisor.py", str(operation_id)]
        if config.get("entrypoint") != "python3" or config.get("arguments") != expected:
            raise DriverError("command_identity_changed")
        session = self.sessions.get(exec_id)
        done = (
            session.result.result()
            if session and session.result and session.result.done()
            else None
        )
        if done is not None:
            return {
                "running": bool(data.get("Running")),
                "receipt": done,
                "cleanup_confirmed": done.get("cleanup_confirmed") is True,
            }
        # Only a recorded READY proves this instance actually started. Created
        # but never started exec instances also report Running=false/ExitCode=0.
        cleaned = (
            (bool(supervisor) or user_start_disallowed)
            and data.get("Running") is False
            and data.get("ExitCode") == 0
        )
        return {"running": bool(data.get("Running")), "receipt": None, "cleanup_confirmed": cleaned}
