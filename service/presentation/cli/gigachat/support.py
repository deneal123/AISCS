"""Bounded diagnostics shared by opt-in GigaChat live smoke commands."""

from __future__ import annotations

from service.domain.client.models.catalog import ModelCatalogSource
from service.domain.client.models.requirements import (
    ModelQualification,
    ModelRequirement,
    ProviderQualificationStatus,
)
from service.domain.client.protocol import ProviderFailureCode, classify_provider_failure
from service.domain.client.providers.gigachat import adapter as gigachat
from service.domain.client.registry import qualify_model

_SMOKE_FAILURE_CODES = (
    frozenset(code.value for code in ProviderFailureCode)
    | frozenset(code.value for code in ProviderQualificationStatus)
    | frozenset(
        {
            "smoke_failed",
            "invalid_smoke_input",
            "artifact_missing",
            "terminal_invalid",
            "model_mismatch",
            "stage_contract_invalid",
            "provider_unavailable",
            "selected_model_unavailable",
            "provider_mismatch",
            "document_not_ready",
            "usage_missing",
            "artifact_contract_invalid",
            "artifact_integrity_invalid",
            "model_missing",
            "case_unknown",
            "tool_count_invalid",
            "grounding_not_activated",
            "grounding_not_satisfied",
            "provider_not_pinned",
            "private_metadata_leak",
            "workspace_content_mismatch",
            "workspace_billing_invalid",
            "validation_failed",
            "function_call_missing",
            "provider_state_missing",
            "provider_not_configured",
        }
    )
)


class GigaChatSmokeFailure(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = (
            reason_code
            if type(reason_code) is str and reason_code in _SMOKE_FAILURE_CODES
            else "smoke_failed"
        )
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
    try:
        explicit = getattr(exc, "reason_code", None)
    except Exception:  # noqa: BLE001 - unknown properties cannot break diagnostics
        explicit = None
    if type(explicit) is str and explicit in _SMOKE_FAILURE_CODES:
        return explicit
    return classify_provider_failure(exc, provider="gigachat").code.value


__all__ = [
    "GigaChatSmokeFailure",
    "bounded_failure_code",
    "require_chat_model",
    "require_qualified_model",
    "require_tool_model",
]
