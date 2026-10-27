"""Separate real agents app with strict model-only HTTP interception."""

import asyncio
import logging
import os
import sys

import uvicorn
from fastapi import Header

from scripts.harness_live.model_transport import ScriptedProvider


async def main():
    logging.disable(logging.CRITICAL)
    if os.environ.get("HARNESS_ACCEPTANCE_SCENARIO") in {"read_change", "question_change"}:
        from service.settings import config

        selected = os.environ["HARNESS_ACCEPTANCE_PROVIDER"]
        # Изолированный процесс не читает health-блокировки основного dev Redis.
        config.redis.enabled = False
        config.agents.llm_provider = selected
        config.agents.provider_enabled = {
            name: name == selected
            for name in ("gigachat", "routerai", "openai", "openrouter", "mws", "local")
        }
        if selected == "openai":
            config.agents.openai_api_key = "acceptance-no-real-provider-credential"
    if os.environ.get("HARNESS_ACCEPTANCE_SCENARIO") in {"refine", "lesson_reuse"}:
        from service.settings import config

        config.agents.harness_refinement_enabled = True
    provider = ScriptedProvider()
    from scripts.harness_live.restart import install_restart, restore_transport

    restore_transport(provider)
    provider.install()
    from service.main import app
    from service.presentation.deps import internal_auth
    from service.settings import config

    install_restart(app, provider)
    from scripts.harness_live.run_observations import install_run_observations

    install_run_observations(app)

    @app.post("/__harness_acceptance__/resume-tuning", include_in_schema=False)
    async def resume_tuning(authorization: str | None = Header(default=None)):
        internal_auth(authorization)
        # Только изолированный сервер приёмки; production-приложение этого пути не имеет.
        config.agents.chat_max_tokens = 128
        return {"max_tokens": config.agents.chat_max_tokens}

    @app.get("/__harness_acceptance__/transport", include_in_schema=False)
    async def transport_status(authorization: str | None = Header(default=None)):
        internal_auth(authorization)
        return {
            "completions": provider.completions,
            "tool_names": provider.tool_names,
            "blocked_requests": provider.blocked_requests,
            "oauth": provider.oauth,
            **(
                {"read_barrier_waiting": provider.read_barrier_waiting}
                if provider.scenario == "read_change"
                else {}
            ),
        }

    @app.post("/__harness_acceptance__/release-read", include_in_schema=False)
    async def release_read(authorization: str | None = Header(default=None)):
        internal_auth(authorization)
        assert provider.scenario == "read_change" and provider.read_barrier_waiting
        provider.release_read.set()
        return {"released": True}

    server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=8091, access_log=False, log_level="critical")
    )
    task = asyncio.create_task(server.serve())
    await asyncio.to_thread(sys.stdin.buffer.read, 1)
    server.should_exit = True
    await task


if __name__ == "__main__":
    asyncio.run(main())
