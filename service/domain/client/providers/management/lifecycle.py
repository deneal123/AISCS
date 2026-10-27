"""Lifecycle cleanup, separate from provider discovery and model selection."""

import asyncio


async def drain_provider_generations() -> None:
    """Close retired clients; an individual failure must not prevent other cleanup."""
    from service.domain.client.registry import PROVIDER_MODULES

    await asyncio.gather(
        *(
            runtime.drain_generations()
            for module in PROVIDER_MODULES.values()
            if (runtime := getattr(module, "_RUNTIME", None)) is not None
            and hasattr(runtime, "drain_generations")
        ),
        return_exceptions=True,
    )
