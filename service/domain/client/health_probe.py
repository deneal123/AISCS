"""Bounded provider probe assembled independently from health orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .model_requirements import ModelRequirement


@dataclass(frozen=True, slots=True)
class ProviderProbeContext:
    known_down: frozenset[str]
    force_probe: bool
    timeout_sec: float


def generation_summary(runtime: Any) -> dict[str, str | int]:
    manager = getattr(runtime, "generations", None)
    if manager is None:
        return {"status": "unavailable", "retired_count": 0, "leased_count": 0}
    return {
        "status": manager.current.status.value,
        "retired_count": manager.retired_count,
        "leased_count": manager.leased_count,
    }


def operation_status(catalog: Any, capability: str) -> str:
    if any(record.supports(capability) for record in catalog.model_records()):
        return (
            "compatible_unverified" if catalog.source.value == "static_fallback" else "compatible"
        )
    return "no_compatible_model"


async def _reach(client: Any, model: str) -> None:
    await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
        stream=False,
    )


def _catalog_summary(catalog: Any) -> dict[str, str | int | bool]:
    return {
        "source": catalog.source.value,
        "status": catalog.status.value,
        "fresh": catalog.fresh,
        "model_count": catalog.model_count,
    }


async def _qualification_summary(name: str, catalog: Any) -> tuple[Any, dict[str, str]]:
    from .registry import qualify_model

    chat, tools, vision = await asyncio.gather(
        qualify_model(name, requirement=ModelRequirement(), catalog=catalog),
        qualify_model(name, requirement=ModelRequirement(tools=True), catalog=catalog),
        qualify_model(name, requirement=ModelRequirement(vision=True), catalog=catalog),
    )
    return chat, {
        "chat": chat.status.value,
        "tools": tools.status.value,
        "vision": vision.status.value,
        "image_output": operation_status(catalog, "image_output"),
        "embeddings": operation_status(catalog, "embeddings"),
        "transcription": operation_status(catalog, "transcription"),
    }


def _configuration_failure(name: str, module: Any, generation: dict) -> tuple[str, dict]:
    config_error = getattr(module, "configuration_error", lambda: None)()
    if config_error:
        return name, {
            "configured": True,
            "reachable": False,
            "error": "tls_config" if config_error == "tls_config" else "internal",
            "reason": "ошибка конфигурации TLS",
            "generation": generation,
        }
    return name, {
        "configured": True,
        "reachable": False,
        "error": "unavailable",
        "generation": generation,
    }


async def probe_provider(name: str, context: ProviderProbeContext) -> tuple[str, dict]:
    """Probe one provider without exposing model payloads or configuration material."""

    from .health import classify_provider_error, provider_error_detail
    from .registry import get_provider_model_catalog, get_provider_module, is_configured

    if not is_configured(name):
        return name, {"configured": False, "reachable": False}
    if name in context.known_down:
        return name, {
            "configured": True,
            "reachable": False,
            "reason": "provider is temporarily unavailable",
            "circuit_open": True,
        }
    module = get_provider_module(name)
    client = getattr(module, "OPENAI_CLIENT", None) if module else None
    runtime = getattr(module, "_RUNTIME", None) if module else None
    generation = generation_summary(runtime)
    if client is None:
        return _configuration_failure(name, module, generation)

    safe_catalog: dict[str, str | int | bool] | None = None
    safe_qualification: dict[str, str] | None = None
    try:
        async with asyncio.timeout(context.timeout_sec):
            catalog = await get_provider_model_catalog(name, force_refresh=context.force_probe)
            safe_catalog = _catalog_summary(catalog)
            chat, safe_qualification = await _qualification_summary(name, catalog)
            if chat.model is not None:
                await _reach(client, chat.model)
        result = {
            "configured": True,
            "reachable": chat.model is not None,
            "catalog": safe_catalog,
            "qualification": safe_qualification,
            "generation": generation,
        }
        if chat.model is None:
            result["error"] = chat.status.value
        return name, result
    except Exception as exc:  # noqa: BLE001 - output uses bounded diagnostics only
        failure: dict[str, Any] = {
            "configured": True,
            "reachable": False,
            "error": provider_error_detail(exc),
            "reason": classify_provider_error(exc),
            "generation": generation,
        }
        if safe_catalog is not None:
            failure["catalog"] = safe_catalog
        if safe_qualification is not None:
            failure["qualification"] = safe_qualification
        return name, failure


__all__ = ["ProviderProbeContext", "generation_summary", "operation_status", "probe_provider"]
