"""Regression coverage for the autonomous workflow catalog persistence boundary."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from service.services.chat.persistence import workflow_catalog


class _Result:
    def __init__(self, value=None):
        self.value = value
        self.rowcount = 0

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value


class _ObservationSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.successes = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "SELECT id FROM profile.workflow_catalog WHERE" in sql:
            return _Result(None)
        if "SELECT count(*) FROM profile.workflow_catalog_examples" in sql:
            self.successes += 1
            return _Result(self.successes)
        return _Result()


def test_fingerprint_binds_exact_step_order_and_calculated_cost_class():
    steps = ["web_search", "general"]

    assert workflow_catalog.chain_fingerprint(steps, "paid") == workflow_catalog.chain_fingerprint(
        steps, "paid"
    )
    assert workflow_catalog.chain_fingerprint(steps, "paid") != workflow_catalog.chain_fingerprint(
        list(reversed(steps)), "paid"
    )
    assert workflow_catalog.chain_fingerprint(steps, "paid") != workflow_catalog.chain_fingerprint(
        steps, "cheap"
    )


@pytest.mark.asyncio
async def test_catalog_is_created_only_after_three_successful_identical_chains():
    session = _ObservationSession()

    for _ in range(3):
        await workflow_catalog.observe(
            session,
            steps=["web_search", "general"],
            cost_class="paid",
            request_text="точный внутренний запрос",
            user_id="user-1",
            thread_id="thread-1",
        )

    catalog_inserts = [
        sql for sql, _ in session.calls if "INSERT INTO profile.workflow_catalog " in sql
    ]
    outbox_inserts = [
        sql for sql, _ in session.calls if "INSERT INTO profile.workflow_catalog_outbox" in sql
    ]
    assert len(catalog_inserts) == 1
    assert len(outbox_inserts) == 1
    assert all("request_text" not in sql for sql in catalog_inserts + outbox_inserts)


@pytest.mark.asyncio
async def test_feedback_upsert_is_idempotent_by_execution_and_user():
    class _Session:
        def __init__(self):
            self.sql: list[str] = []

        async def execute(self, statement, _params=None):
            query = str(statement)
            self.sql.append(query)
            return (
                _Result("execution-id")
                if "SELECT id FROM profile.workflow_catalog_executions" in query
                else _Result()
            )

    session = _Session()
    assert await workflow_catalog.apply_feedback(
        session,
        thread_id="thread-1",
        content_key="content-key",
        user_id="user-1",
        rating="like",
    )
    assert any("ON CONFLICT (execution_id, user_id)" in query for query in session.sql)


@pytest.mark.asyncio
async def test_obsolete_pin_endpoint_returns_explicit_gone():
    from service.services.chat.presentation.routers.chat_api import workspace_api

    class _Service:
        async def ensure_thread_owner(self, *_args):
            return None

    with pytest.raises(HTTPException) as caught:
        await workspace_api.pin_workflow(
            thread_id="thread-1",
            profile=type("Profile", (), {"user_id": "user-1"})(),
            service=_Service(),
        )

    assert caught.value.status_code == 410
    assert caught.value.detail == "workflow_catalog_autonomous"


@pytest.mark.asyncio
async def test_outbox_claim_uses_skip_locked_lease_and_bounded_retry_class():
    class _Rows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def __iter__(self):
            return iter(self.rows)

    class _Session:
        def __init__(self):
            self.calls: list[tuple[str, dict]] = []

        async def execute(self, statement, params=None):
            self.calls.append((str(statement), params or {}))
            return _Rows([])

    session = _Session()
    assert await workflow_catalog.claim_pending_outbox(session, lease_sec=120) == []
    claim_sql, claim_params = session.calls[-1]
    assert "FOR UPDATE SKIP LOCKED" in claim_sql
    assert "lease_until" in claim_sql and "lease_token" in claim_sql
    assert claim_params["lease_sec"] == 120

    await workflow_catalog.mark_outbox(
        session,
        outbox_id="outbox-id",
        lease_token="00000000-0000-0000-0000-000000000001",
        delivered=False,
        error_class="timeout",
        retry_max_sec=90,
    )
    retry_sql, retry_params = session.calls[-1]
    assert "power(2" in retry_sql and "lease_token" in retry_sql
    assert retry_params["error_class"] == "timeout"
    assert "last_error = NULL" in retry_sql


def test_outbox_aggregate_query_never_selects_exact_request_text():
    # The background metric may contain depth/age only, not retained examples.
    import inspect

    source = inspect.getsource(workflow_catalog.outbox_snapshot)
    assert "request_text" not in source


@pytest.mark.asyncio
async def test_outbox_delivery_classifies_sidecar_failure_without_raising(monkeypatch):
    from service.infrastructure.agents_client import workflow_catalog as delivery
    from service.infrastructure.sidecar import SidecarTimeout

    class _Client:
        async def request_json(self, *_args, **_kwargs):
            raise SidecarTimeout("agents", "timeout")

    monkeypatch.setattr(delivery, "_client", lambda _config: _Client())
    result = await delivery.deliver(None, {"action": "delete", "index_point_id": "point-1"})
    assert not result.delivered
    assert result.error_class == "timeout"
