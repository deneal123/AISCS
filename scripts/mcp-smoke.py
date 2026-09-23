from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def exercise() -> None:
    parameters = StdioServerParameters(
        command="uv.exe",
        args=["run", "--directory", str(ROOT), "--frozen", "publications-mcp"],
    )
    async with Client(parameters) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        status = await client.call_tool("status", {})
        if status.is_error or status.structured_content["integrity"]["ok"] is not True:
            raise RuntimeError("MCP status integrity failed")
        print(
            json.dumps(
                {
                    "ok": True,
                    "tools": len(tools.tools),
                    "resources": len(resources.resources),
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(exercise())
