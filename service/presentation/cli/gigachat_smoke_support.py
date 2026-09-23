"""Bounded diagnostics shared by opt-in GigaChat live smoke commands."""

from __future__ import annotations

from service.domain.client.model_catalog import ModelCatalogSource
from service.domain.client.model_requirements import ModelQualification, ModelRequirement
from service.domain.client.protocol import classify_provider_failure
from service.domain.client.providers import gigachat
from service.domain.client.registry import qualify_model


class GigaChatSmokeFailure(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = str(reason_code)
        super().__init__(self.reason_code)


async def require_qualified_model(
    model: str,
    *,
    requirement: ModelRequirement,
) -> ModelQualification:
    """Require a live-discovered model satisfying the requested capabilities."""

    try:
        catalog = await gigachat._RUNTIME.model_catalog(force_refresh=True)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001 - converted at the operational boundary
        failure = classify_provider_failure(exc, provider="gigachat")
        raise GigaChatSmokeFailure(failure.code.value) from None
    if catalog.source is not ModelCatalogSource.LIVE:
        raise GigaChatSmokeFailure("catalog_unavailable")
    decision = await qualify_model(
        "gigachat",
        prefer=model,
        requirement=requirement,
        catalog=catalog,
    )
    if decision.model != model or not decision.compatible:
        raise GigaChatSmokeFailure(decision.status.value)
    print(
        "qualification: provider=gigachat "
        f"model={model} source={catalog.source.value} status={decision.status.value} "
        f"models={catalog.model_count}"
    )
    return decision


async def require_chat_model(model: str) -> ModelQualification:
    """Compatibility facade for a live-discovered GigaChat chat model."""

    return await require_qualified_model(model, requirement=ModelRequirement())


async def require_tool_model(model: str) -> ModelQualification:
    return await require_qualified_model(
        model,
        requirement=ModelRequirement(tools=True),
    )


def bounded_failure_code(exc: Exception) -> str:
    explicit = str(getattr(exc, "reason_code", "") or "").strip()
    if explicit:
        return explicit
    return classify_provider_failure(exc, provider="gigachat").code.value


__all__ = [
    "GigaChatSmokeFailure",
    "bounded_failure_code",
    "require_chat_model",
    "require_qualified_model",
    "require_tool_model",
]
