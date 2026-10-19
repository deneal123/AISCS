"""Idempotent deletion of an already-known immutable Docker container identity."""

import re
from collections.abc import Awaitable, Callable

from drivers.base import ContainerRef, DriverError


async def destroy_known_container(
    ref: ContainerRef,
    run: Callable[..., Awaitable[tuple[int, str, str]]],
) -> None:
    code, _, _ = await run("rm", "-f", ref.container_id)
    if code == 0:
        return
    # A failed rm, inspect or daemon connection is not proof of absence. Only
    # a successful exact-ID inventory can settle an already-removed container.
    # Never use an empty/partial identifier, mutable name or response text here.
    if ref.driver != "docker" or not re.fullmatch(r"[0-9a-f]{64}", ref.container_id):
        raise DriverError("docker destroy failed")
    code, output, _ = await run(
        "ps",
        "--all",
        "--no-trunc",
        "--filter",
        f"id={ref.container_id}",
        "--format",
        "{{json .ID}}",
    )
    if code != 0 or output.strip():
        raise DriverError("docker destroy failed")
