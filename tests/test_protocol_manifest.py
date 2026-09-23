from service.infrastructure.agents_client.contracts.events import (
    AUTO_REASON_CODES,
    ERROR_CATEGORIES,
    ERROR_CODES,
    STATUS_FAMILIES,
    EventType,
)
from service.infrastructure.agents_client.contracts.protocol_manifest import (
    load_protocol_manifest,
)
from service.infrastructure.agents_client.contracts.run import AgentRunInput
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.presentation.routers.chat_api.work_snapshot import (
    WORK_SNAPSHOT_VERSION,
)
from service.services.chat.presentation.routers.chat_api.workspace_metrics import _STATUSES
from service.services.chat.presentation.ws.chat_ws.metrics import (
    _PROVIDER_QUALIFICATION_STATUSES,
    _RUN_INTEGRITY_REASONS,
    _STREAM_PROTOCOL_STAGES,
    _USAGE_INTEGRITY_REASONS,
)


def test_protocol_manifest_matches_backend_consumers() -> None:
    manifest = load_protocol_manifest()

    assert manifest.version == "s33-v1"
    assert manifest.run_input_fields == frozenset(AgentRunInput.model_fields)
    assert manifest.event_types == frozenset(item.value for item in EventType)
    assert manifest.auto_reason_codes == AUTO_REASON_CODES
    assert manifest.error_codes == ERROR_CODES
    assert manifest.error_categories == ERROR_CATEGORIES
    assert manifest.status_families == STATUS_FAMILIES
    assert manifest.required_result_fields == frozenset({"reply"})
    assert manifest.work_snapshot_version == WORK_SNAPSHOT_VERSION
    assert {"__result__", "__error__"} == manifest.terminal_keys
    assert manifest.run_phases == tuple(item.value for item in RunPhase)
    assert manifest.run_integrity_reasons == _RUN_INTEGRITY_REASONS - {"unknown"}
    assert manifest.usage_integrity_reasons == _USAGE_INTEGRITY_REASONS - {"unknown"}
    assert manifest.provider_catalog_sources == {"live", "stale", "static_fallback"}
    assert manifest.provider_catalog_statuses == {
        "available",
        "empty",
        "auth",
        "timeout",
        "malformed",
        "unavailable",
    }
    assert manifest.provider_capability_evidence_sources == {
        "provider_metadata",
        "local_profile",
        "trusted_catalog",
        "static_fallback",
        "unknown",
    }
    assert manifest.provider_qualification_statuses == _PROVIDER_QUALIFICATION_STATUSES
    assert manifest.provider_model_capabilities == {
        "chat",
        "tools",
        "vision",
        "image_output",
        "embeddings",
        "transcription",
    }
    assert manifest.provider_operations == {
        "chat",
        "tool_chat",
        "vision_input",
        "image_output",
        "embeddings",
        "transcription",
    }
    assert manifest.provider_admission_statuses == {
        "admitted",
        "admitted_unverified",
        "no_compatible_model",
        "catalog_unavailable",
        "client_unavailable",
        "tool_schema",
        "tool_choice",
        "operation_unsupported",
        "provider_protocol",
    }
    assert manifest.provider_generation_statuses == {"ready", "unavailable", "retired"}
    assert manifest.stream_protocol_stages == _STREAM_PROTOCOL_STAGES
    assert manifest.workspace_operation_statuses == _STATUSES
