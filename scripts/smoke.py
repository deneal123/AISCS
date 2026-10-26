"""Exercise HTTP in-process and the real stdio MCP transport without Docker."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.interfaces.http import create_app  # noqa: E402 -- runnable from the checkout


async def main() -> None:
    with TestClient(create_app()) as http:
        ready = http.get("/ready")
        assert ready.status_code == 200 and ready.json()["ok"]
        assert http.get("/v1/sources", params={"q": "ECAP", "limit": 3}).status_code == 200
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "service.interfaces.mcp"], cwd=str(ROOT)
    )
    async with Client(parameters) as client:
        tools = await client.list_tools()
        status = await client.call_tool("status", {})
        assert not status.is_error
    print(json.dumps({"http": "ASGI in-process", "mcp": "stdio", "tools": len(tools.tools)}))


if __name__ == "__main__":
    asyncio.run(main())
