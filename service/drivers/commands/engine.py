"""Fixed Unix-socket Engine transport; never accepts model URLs or retries effects."""

import asyncio
import json
import re
from dataclasses import dataclass

import httpx

from drivers.base import DriverError

SOCKET = "/var/run/docker.sock"
IDENTITY = re.compile(r"^[a-f0-9]{64}$")


def identity(value):
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        raise DriverError("command_identity_invalid")
    return value


@dataclass
class ExecStream:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    pending: bytes = b""

    async def message(self, timeout=10):
        async with asyncio.timeout(timeout):
            while b"\n" not in self.pending:
                header = await self.reader.readexactly(8)
                size = int.from_bytes(header[4:], "big")
                if header[0] != 1 or header[1:4] != b"\0\0\0" or size > 262144:
                    raise DriverError("command_stream_invalid")
                self.pending += await self.reader.readexactly(size)
                if len(self.pending) > 262144:
                    raise DriverError("command_stream_limit")
            line, self.pending = self.pending.split(b"\n", 1)
            value = json.loads(line)
            if not isinstance(value, dict):
                raise DriverError("command_stream_invalid")
            return value

    async def send(self, value):
        self.writer.write(json.dumps(value, separators=(",", ":")).encode() + b"\n")
        await self.writer.drain()

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, OSError):
            pass


class Engine:
    def __init__(self):
        self.version = None

    async def request(self, method, path, body=None):
        try:
            transport = httpx.AsyncHTTPTransport(uds=SOCKET, retries=0)
            async with httpx.AsyncClient(
                transport=transport, timeout=10, trust_env=False
            ) as client:
                response = await client.request(method, "http://docker" + path, json=body)
                if response.status_code not in {200, 201} or len(response.content) > 262144:
                    raise DriverError("command_engine_failed")
                data = response.json()
                if not isinstance(data, dict):
                    raise DriverError("command_engine_response_invalid")
                return data
        except (httpx.HTTPError, ValueError, OSError):
            raise DriverError("command_engine_unavailable") from None

    async def prefix(self):
        if self.version is None:
            data = await self.request("GET", "/version")
            try:
                supported = tuple(int(part) for part in data["ApiVersion"].split("."))
                minimum = tuple(int(part) for part in data.get("MinAPIVersion", "1.24").split("."))
                if len(supported) != 2 or len(minimum) != 2:
                    raise ValueError
                selected = min(supported, (1, 51))
                if selected < max(minimum, (1, 44)):
                    raise ValueError
                self.version = "/v" + ".".join(map(str, selected))
            except (KeyError, ValueError, TypeError, AttributeError):
                raise DriverError("command_engine_version_unsupported") from None
        return self.version

    async def create(self, container, operation):
        data = await self.request(
            "POST",
            await self.prefix() + f"/containers/{identity(container)}/exec",
            {
                "AttachStdin": True,
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": False,
                "Privileged": False,
                "User": "65534:65534",
                "WorkingDir": "/workspace",
                "Cmd": ["python3", "-I", "-S", "/opt/gpthub-harness/supervisor.py", str(operation)],
            },
        )
        return identity(data.get("Id"))

    async def inspect(self, exec_id, container):
        data = await self.request("GET", await self.prefix() + f"/exec/{identity(exec_id)}/json")
        if data.get("ID") != exec_id or data.get("ContainerID") != identity(container):
            raise DriverError("command_identity_changed")
        if (
            type(data.get("Running")) is not bool
            or "ExitCode" not in data
            or (data["ExitCode"] is not None and type(data["ExitCode"]) is not int)
            or not isinstance(data.get("ProcessConfig"), dict)
        ):
            raise DriverError("command_engine_response_invalid")
        # Engine reports null before start (and may do so while running).
        # An unknown exit code never satisfies the cleanup exit_code == 0 check.
        return data

    async def start(self, exec_id):
        prefix = await self.prefix()
        reader, writer = await asyncio.open_unix_connection(SOCKET, limit=262144)
        try:
            body = b'{"Detach":false,"Tty":false}'
            request = (
                f"POST {prefix}/exec/{identity(exec_id)}/start HTTP/1.1\r\n"
                "Host: docker\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n"
            ).encode() + body
            writer.write(request)
            await writer.drain()
            async with asyncio.timeout(10):
                header = await reader.readuntil(b"\r\n\r\n")
            if not header.startswith(b"HTTP/1.1 101 "):
                raise DriverError("command_start_unknown")
            return ExecStream(reader, writer)
        except BaseException:
            writer.close()
            raise
