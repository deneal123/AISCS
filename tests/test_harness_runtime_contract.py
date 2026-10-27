"""Offline private-protocol, tariff and admission regressions. No stand access."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from service.services.billing.application.frozen_pricing import freeze_pricing
from service.services.billing.application.pricing_service import PricingService
from service.services.chat.application.harness_capability import HarnessOwner, authorize, issue
from service.services.chat.persistence.harness.runtime import (
    HarnessRuntimeRepository,
    _sealed_state,
)
from service.services.chat.presentation.routers.harness import router
from service.shared.harness_protocol import (
    Admission,
    Continuation,
    ContractProposal,
    Exchange,
    HarnessFailure,
    Snapshot,
)


def admission():
    return Admission(
        task_id=str(uuid4()),
        project_id="project",
        generation="generation",
        surface="ide",
        goal="PRIVATE_GOAL",
        source_revision="r1",
        actions=["read", "write", "exec"],
        credit_limit=100,
        reservation_id=str(uuid4()),
    )


def owner():
    return HarnessOwner(
        task_id=str(uuid4()),
        job_id=str(uuid4()),
        user_id=str(uuid4()),
        thread_id=str(uuid4()),
        attempt_id=str(uuid4()),
        epoch=2,
        project_id="project",
        generation="generation",
    )


def test_capability_is_attempt_epoch_project_bound_and_wrong_audience_is_rejected():
    scope = owner()
    token = issue(scope)
    assert authorize(token) == scope
    with pytest.raises(HarnessFailure, match="harness_forbidden"):
        authorize(token[:-6] + "broken")


def test_change_contract_cannot_drop_mandatory_execution_verification():
    current = Snapshot(admission=admission())
    proposal = ContractProposal(
        kind="change",
        criteria=[
            {"criterion_id": "source", "kind": "file", "target": "hello.py"},
        ],
    )
    state = _sealed_state(current, proposal)
    assert [item.kind for item in state.contract.criteria] == ["file", "command"]
    assert state.contract.goal == current.admission.goal
    assert state.contract.credit_limit == current.admission.credit_limit


def test_analysis_stays_read_only_without_an_artificial_write():
    state = _sealed_state(
        Snapshot(admission=admission()),
        ContractProposal(
            kind="analysis",
            criteria=[{"criterion_id": "read", "kind": "read", "target": "README.md"}],
        ),
    )
    assert state.contract.actions == ("read",)


@pytest.mark.parametrize(
    "kind,criteria",
    [
        ("analysis", [{"criterion_id": "source", "kind": "file", "target": "PRIVATE_PATH"}]),
        ("change", [{"criterion_id": "source", "kind": "read", "target": "PRIVATE_PATH"}]),
        (
            "change",
            [
                {"criterion_id": "same", "kind": "file", "target": "PRIVATE_PATH"},
                {"criterion_id": "same", "kind": "file", "target": "other"},
            ],
        ),
    ],
)
def test_bad_criteria_are_contract_failures_not_checkpoint_outages(kind, criteria):
    with pytest.raises(HarnessFailure, match="task_contract_invalid") as raised:
        _sealed_state(
            Snapshot(admission=admission()), ContractProposal(kind=kind, criteria=criteria)
        )
    assert "PRIVATE_PATH" not in str(raised.value)


@pytest.mark.parametrize(
    "raw",
    [
        {"opcode": "state", "state": {}},
        {"opcode": "grant"},
        {"opcode": "dispatch", "operation_id": "not-a-uuid"},
        {"opcode": "result", "capability": "PRIVATE"},
    ],
)
def test_opcode_payload_is_closed(raw):
    with pytest.raises(ValidationError):
        Exchange.model_validate(raw)


def test_continuation_accepts_pending_tools_only_at_the_tool_boundary():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call1",
                    "function": {
                        "name": "ide_read_file",
                        "arguments": '{"path":"README.md"}',
                    },
                }
            ],
        }
    ]
    assert Continuation(messages=messages, phase="tools").conversation()[0]["tool_calls"]
    with pytest.raises(ValidationError):
        Continuation(messages=messages, phase="model")
    with pytest.raises(ValidationError):
        Continuation(messages=[{"role": "tool", "tool_call_id": "missing", "content": "private"}])


@pytest.mark.asyncio
@pytest.mark.parametrize("public_handlers", [False, True])
@pytest.mark.parametrize("endpoint", ["exchange", "commands"])
async def test_private_route_authenticates_before_validation_and_never_echoes_body(
    public_handlers, endpoint
):
    app = FastAPI()
    app.include_router(router)
    if public_handlers:
        from service.shared.presentation.handlers.exceptions_handlers import (
            setup_exception_handlers,
        )

        setup_exception_handlers(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/internal/harness/v1/{endpoint}", content="PRIVATE_INVALID_JSON"
        )
        assert response.status_code == 403
        assert response.headers["Cache-Control"] == "private, no-store"
        response = await client.post(
            f"/internal/harness/v1/{endpoint}",
            content="PRIVATE_INVALID_JSON",
            headers={"Authorization": "Bearer " + issue(owner())},
        )
        assert response.status_code == 409
        assert "PRIVATE" not in response.text
        assert response.json()["detail"]["code"] == "harness_request_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [
        "budget_exhausted",
        "cost_unknown",
        "harness_fenced",
        "binding_changed",
        "dispatch_disabled",
        "checkpoint_unavailable",
    ],
)
async def test_public_error_owner_cannot_change_private_failure_codes(monkeypatch, code):
    from service.shared.presentation.handlers.exceptions_handlers import setup_exception_handlers

    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(router)
    app.state.container = SimpleNamespace(infra=SimpleNamespace(pg_connector=None))
    monkeypatch.setattr(
        HarnessRuntimeRepository, "exchange", AsyncMock(side_effect=HarnessFailure(code))
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/harness/v1/exchange",
            json={"opcode": "state"},
            headers={"Authorization": "Bearer " + issue(owner())},
        )
    assert response.status_code == (503 if code == "checkpoint_unavailable" else 409)
    assert response.json() == {"detail": {"code": code}}
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"


@pytest.mark.asyncio
async def test_frozen_tariff_uses_cumulative_existing_formula_and_ignores_later_config_changes():
    config = SimpleNamespace(
        min_margin=1,
        margin_multiplier=1,
        complexity_factor_complex=2,
        credit_unit_rub="0.01",
        min_credits_per_request=10,
        default_price_in_rub_per_1k="1",
        default_price_out_rub_per_1k="2",
        class_prices_rub_per_1k={},
        tool_surcharge_rub={"workspace_tool": "1"},
    )
    pricing = PricingService(SimpleNamespace(fetch_pricing_map=AsyncMock(return_value={})), config)
    tariff = await freeze_pricing(pricing)
    first = {"model": "test", "prompt": 1, "completion": 0}
    assert tariff.price([first]).credits == 10
    assert tariff.price([first, first]).credits == 10  # minimum once, not once per call
    expected = await pricing.price_request(
        per_call_usage=[first, first], tools=["workspace_tool"], is_complex=False
    )
    assert tariff.price([first, first], ["workspace_tool", "workspace_tool"]) == expected
    encoded = tariff.model_dump_json()
    config.default_price_in_rub_per_1k = "9999"
    assert tariff.model_validate_json(encoded).price([first]).credits == 10
    assert "PRIVATE_GOAL" not in json.dumps(tariff.model_dump(mode="json"))


def test_runtime_migration_compiles_postgres_ddl_without_connecting():
    import importlib.util
    import io
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "alembic/versions/044_harness_runtime.py"
    spec = importlib.util.spec_from_file_location("harness_runtime_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    ddl = output.getvalue()
    assert "CREATE TABLE profile.harness_grant" in ddl
    assert "FOREIGN KEY(active_job_id) REFERENCES profile.user_launch" in ddl
    assert "ADD COLUMN usage_history JSONB" in ddl
    assert "DROP TABLE profile.harness_grant" in ddl
    assert migration.down_revision == "043_harness_state"
