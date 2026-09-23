from service.contracts import ANSWER_USAGE_KINDS, RESULT_FIELDS, SERVICE_USAGE_KINDS
from service.domain.client.model_catalog import (
    CapabilityEvidenceSource,
    ModelCapability,
    ModelCatalogSource,
    ModelCatalogStatus,
)
from service.domain.client.model_requirements import ProviderQualificationStatus
from service.domain.client.protocol import ProviderFailureCode
from service.domain.client.provider_generation import ProviderGenerationStatus
from service.domain.client.provider_operations import ProviderAdmissionStatus, ProviderOperation
from service.domain.grounding import GroundingFailureCode, GroundingState
from service.domain.integration_failure import (
    IntegrationFailureCode,
    IntegrationSource,
    StatusFamily,
)
from service.domain.runners.tool_runtime.contracts import ToolCallStatus
from service.domain.usage_ledger import USAGE_INTEGRITY_REASONS, UsageKind
from service.events import (
    AUTO_REASON_CODES,
    ERROR_CATEGORIES,
    ERROR_CODES,
    STATUS_FAMILIES,
    EventType,
)
from service.protocol_manifest import load_protocol_manifest
from service.schemas.run import AgentRunInput


def test_protocol_manifest_matches_agents_runtime_contracts() -> None:
    manifest = load_protocol_manifest()

    assert manifest.version == "s33-v1"
    assert manifest.run_input_fields == frozenset(AgentRunInput.model_fields)
    assert manifest.run_result_fields == RESULT_FIELDS
    assert manifest.required_result_fields == frozenset({"reply"})
    assert manifest.terminal_keys == frozenset({"__error__", "__result__"})
    assert manifest.event_types == frozenset(item.value for item in EventType)
    assert manifest.auto_reason_codes == AUTO_REASON_CODES
    assert manifest.error_codes == ERROR_CODES
    assert manifest.error_categories == ERROR_CATEGORIES
    assert manifest.status_families == STATUS_FAMILIES
    assert frozenset(item.value for item in ProviderFailureCode) <= manifest.error_codes
    assert frozenset(item.value for item in IntegrationFailureCode) <= manifest.error_codes
    assert frozenset(item.value for item in IntegrationSource) == manifest.error_categories
    assert frozenset(item.value for item in StatusFamily) == manifest.status_families
    assert manifest.usage_kinds == frozenset(item.value for item in UsageKind)
    assert manifest.usage_kinds - {UsageKind.OTHER.value} == (
        SERVICE_USAGE_KINDS | ANSWER_USAGE_KINDS
    )
    assert manifest.usage_integrity_reasons == USAGE_INTEGRITY_REASONS
    assert manifest.provider_catalog_sources == frozenset(item.value for item in ModelCatalogSource)
    assert manifest.provider_catalog_statuses == frozenset(
        item.value for item in ModelCatalogStatus
    )
    assert manifest.provider_capability_evidence_sources == frozenset(
        item.value for item in CapabilityEvidenceSource
    )
    assert manifest.provider_qualification_statuses == frozenset(
        item.value for item in ProviderQualificationStatus
    )
    assert manifest.provider_model_capabilities == frozenset(item.value for item in ModelCapability)
    assert manifest.provider_operations == frozenset(item.value for item in ProviderOperation)
    assert manifest.provider_admission_statuses == frozenset(
        item.value for item in ProviderAdmissionStatus
    )
    assert manifest.provider_generation_statuses == frozenset(
        item.value for item in ProviderGenerationStatus
    )


def test_protocol_manifest_contains_closed_execution_codes() -> None:
    manifest = load_protocol_manifest()

    assert frozenset(item.value for item in GroundingState) == manifest.grounding_states
    assert frozenset(item.value for item in GroundingFailureCode if item.value) == (
        manifest.grounding_reasons
    )
    assert frozenset(item.value for item in ToolCallStatus) == manifest.tool_outcomes
