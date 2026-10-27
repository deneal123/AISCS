"""Private projection from run admission to one provider call attempt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from service.domain.client.models.requirements import ModelRequirement
from service.domain.client.providers.management.admission import RunProviderAdmission
from service.domain.client.providers.management.operations import (
    ProviderAdmissionStatus,
    ProviderOperation,
)

from ..protocol import ProviderFailure, ProviderFailureCode, ProviderProtocolError
from ..protocol.compiler import ProviderToolCompilationError
from ..registry import _pick_chat_capable_model

_ACCEPTED = {
    ProviderAdmissionStatus.ADMITTED,
    ProviderAdmissionStatus.ADMITTED_UNVERIFIED,
}
_MODEL_FAILURES = {
    ProviderAdmissionStatus.NO_COMPATIBLE_MODEL,
    ProviderAdmissionStatus.OPERATION_UNSUPPORTED,
}


@dataclass(frozen=True, slots=True)
class AdmittedCall:
    client: Any
    model: str | None
    compiled_tools: Any
    status: ProviderAdmissionStatus
    failure: Exception | None

    @property
    def accepted(self) -> bool:
        return self.status in _ACCEPTED and self.client is not None and self.model is not None


def _failure(provider: str, status: ProviderAdmissionStatus) -> Exception:
    if status in {ProviderAdmissionStatus.TOOL_SCHEMA, ProviderAdmissionStatus.TOOL_CHOICE}:
        return ProviderToolCompilationError(status.value)
    if status in {
        ProviderAdmissionStatus.CATALOG_UNAVAILABLE,
        ProviderAdmissionStatus.CLIENT_UNAVAILABLE,
    }:
        code = ProviderFailureCode.REMOTE
    else:
        code = (
            ProviderFailureCode.NO_COMPATIBLE_MODEL
            if status in _MODEL_FAILURES
            else ProviderFailureCode.PROVIDER_PROTOCOL
        )
    return ProviderProtocolError(ProviderFailure(code=code, retryable=False, provider=provider))


def resolve_admitted_call(
    admission: RunProviderAdmission,
    provider: str,
    *,
    operation: ProviderOperation,
    prefer: str | None,
    tools: list[dict] | None,
    tool_choice: Any,
    requirement: ModelRequirement,
) -> AdmittedCall:
    decision = admission.admit(
        provider,
        operation=operation,
        prefer=prefer,
        tools=tools,
        tool_choice=tool_choice,
        requirement=requirement,
        pick_model=_pick_chat_capable_model,
    )
    return AdmittedCall(
        client=decision.client,
        model=decision.model,
        compiled_tools=decision.compiled_tools,
        status=decision.status,
        failure=None if decision.status in _ACCEPTED else _failure(provider, decision.status),
    )


__all__ = ["AdmittedCall", "resolve_admitted_call"]
