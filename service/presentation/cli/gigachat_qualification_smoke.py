"""Sequential opt-in GigaChat model, function and workspace certification."""

from __future__ import annotations

import asyncio

from service.presentation.cli.gigachat_smoke_support import bounded_failure_code
from service.presentation.cli.gigachat_tools_smoke import run_tools_certification
from service.presentation.cli.gigachat_workspace_smoke import run_workspace_certification


async def _main() -> None:
    await run_tools_certification()
    print("certification stage=tool_protocol status=passed")
    await run_workspace_certification(qualify=False)
    print("certification stage=workspace_tools status=passed")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except Exception as exc:  # noqa: BLE001 - operational output must remain bounded
        print(f"gigachat certification: FAILED code={bounded_failure_code(exc)}")
        raise SystemExit(1) from None
    print("gigachat certification: OK")
