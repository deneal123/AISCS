"""Addressable launch never retries GO and never accepts project output as control."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from drivers import docker_cli
from drivers.base import ContainerRef, DriverError
from drivers.commands.engine import Engine, ExecStream, identity
from drivers.commands.lifecycle import CommandSession, DockerCommands


def frame(body):
    data = json.dumps(body).encode() + b"\n"
    return b"\x01\0\0\0" + len(data).to_bytes(4, "big") + data


async def test_docker_frames_keep_nested_user_output_out_of_control():
    reader = asyncio.StreamReader()
    reader.feed_data(frame({"type": "done", "result": {"stdout": '{"type":"ready"}'}}))
    stream = ExecStream(reader, SimpleNamespace())
    message = await stream.message()
    assert message["type"] == "done" and message["result"]["stdout"] == '{"type":"ready"}'


async def test_non_control_stream_is_rejected():
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x02\0\0\0\0\0\0\x02xx")
    with pytest.raises(DriverError, match="command_stream_invalid"):
        await ExecStream(reader, SimpleNamespace()).message()


@pytest.mark.parametrize("value", ["container", "--privileged", "a" * 63, "A" * 64, None])
def test_engine_ids_are_not_command_line_options_or_unbounded_paths(value):
    with pytest.raises(DriverError):
        identity(value)


@pytest.mark.parametrize("exit_code", [None, 0, 1])
async def test_engine_inspect_accepts_unknown_or_integer_exit_code(exit_code):
    engine = Engine()
    engine.version = "/v1.51"
    engine.request = AsyncMock(
        return_value={
            "ID": "b" * 64,
            "ContainerID": "a" * 64,
            "Running": False,
            "ExitCode": exit_code,
            "ProcessConfig": {},
        }
    )
    data = await engine.inspect("b" * 64, "a" * 64)
    assert data["ExitCode"] == exit_code


@pytest.mark.parametrize("exit_code", [False, "0", 0.0, {}])
async def test_engine_inspect_rejects_invalid_exit_code_types(exit_code):
    engine = Engine()
    engine.version = "/v1.51"
    engine.request = AsyncMock(
        return_value={
            "ID": "b" * 64,
            "ContainerID": "a" * 64,
            "Running": False,
            "ExitCode": exit_code,
            "ProcessConfig": {},
        }
    )
    with pytest.raises(DriverError, match="command_engine_response_invalid"):
        await engine.inspect("b" * 64, "a" * 64)


async def test_lost_send_ack_cannot_resend_the_command():
    lifecycle = DockerCommands()
    lifecycle.engine = SimpleNamespace(inspect=AsyncMock(return_value={"Running": True}))
    stream = SimpleNamespace(
        send=AsyncMock(side_effect=OSError()), message=AsyncMock(return_value={}), close=AsyncMock()
    )
    operation = uuid4()
    session = CommandSession(stream, {"pid": 2, "operation_id": str(operation)})
    lifecycle.sessions["b" * 64] = session
    options = {"argv": ["true"], "timeout_sec": 1, "output_limit": 100}
    with pytest.raises(OSError):
        await lifecycle.dispatch(ContainerRef("docker", "a" * 64), operation, "b" * 64, **options)
    with pytest.raises(DriverError, match="command_dispatch_unknown"):
        await lifecycle.dispatch(ContainerRef("docker", "a" * 64), operation, "b" * 64, **options)
    stream.send.assert_awaited_once()
    await session.result


@pytest.mark.parametrize("exit_code", [0, None])
async def test_exit_without_recorded_ready_does_not_prove_cleanup(exit_code):
    operation = uuid4()
    lifecycle = DockerCommands()
    lifecycle.engine = SimpleNamespace(
        inspect=AsyncMock(
            return_value={
                "Running": False,
                "ExitCode": exit_code,
                "ProcessConfig": {
                    "entrypoint": "python3",
                    "arguments": [
                        "-I",
                        "-S",
                        "/opt/gpthub-harness/supervisor.py",
                        str(operation),
                    ],
                },
            }
        )
    )
    status = await lifecycle.status(ContainerRef("docker", "a" * 64), operation, "b" * 64)
    assert not status["cleanup_confirmed"] and status["receipt"] is None
    status = await lifecycle.status(
        ContainerRef("docker", "a" * 64),
        operation,
        "b" * 64,
        supervisor={"pid": 2, "start_time": "123"},
    )
    assert status["cleanup_confirmed"] is (exit_code == 0)
    assert status["receipt"] is None


async def test_stop_runs_as_supervisor_user_without_new_capabilities(monkeypatch):
    driver = docker_cli.DockerCliDriver()
    lifecycle = SimpleNamespace(
        status=AsyncMock(
            side_effect=[
                {"running": True},
                {"running": False, "cleanup_confirmed": True},
            ]
        )
    )
    driver.command_lifecycle = lambda: lifecycle
    execute = AsyncMock(return_value=(0, "", ""))
    monkeypatch.setattr(docker_cli, "_docker", execute)
    data = await driver.stop_command(
        ContainerRef("docker", "a" * 64),
        uuid4(),
        "b" * 64,
        supervisor={"pid": 123, "start_time": "456", "version": 1},
    )
    assert data["cleanup_confirmed"]
    assert execute.await_args.args[:4] == ("exec", "--user", "65534:65534", "a" * 64)
    assert "--privileged" not in execute.await_args.args


async def test_repeated_stop_of_finished_exec_does_not_signal_a_reused_pid(monkeypatch):
    driver = docker_cli.DockerCliDriver()
    driver.command_lifecycle = lambda: SimpleNamespace(
        status=AsyncMock(
            return_value={
                "running": False,
                "cleanup_confirmed": True,
            }
        )
    )
    execute = AsyncMock()
    monkeypatch.setattr(docker_cli, "_docker", execute)
    data = await driver.stop_command(
        ContainerRef("docker", "a" * 64),
        uuid4(),
        "b" * 64,
        supervisor={"pid": 123, "start_time": "456", "version": 1},
    )
    assert data["cleanup_confirmed"]
    execute.assert_not_awaited()
