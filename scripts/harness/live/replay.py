"""Наблюдение исходного оплаченного receipt при изменении настроек после crash."""

import json

import httpx
from sqlalchemy import text


async def change_resume_tuning(container, job, receipt_id):
    from uuid import UUID

    from service.settings import config

    async with container.infra.pg_connector.get_session_context() as db:
        frozen = await db.scalar(
            text(
                "SELECT request FROM profile.harness_grant "
                "WHERE task_id=:job AND operation_id=:operation"
            ),
            {"job": job, "operation": UUID(receipt_id)},
        )
    assert json.loads(frozen["canonical_request"])["max_tokens"] > 128
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.post(
            "http://agents:8091/__harness_acceptance__/resume-tuning",
            headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
        )
        assert response.status_code == 200 and response.json() == {"max_tokens": 128}


def observe_replay(fault, payload, response):
    if payload.get("opcode") != "grant" or not fault.boundary:
        return
    response = response.get("operation") or {}
    call = payload.get("call") or {}
    original = fault.boundary.get("receipt") or {}
    if not original.get("operation_id") or response.get("operation_id") != original["operation_id"]:
        return
    assert call["operation_id"] != original["operation_id"]
    assert json.loads(call["canonical_request"])["max_tokens"] == 128
    from service.shared.harness_protocol import CallReceipt

    assert response["status"] == "succeeded"
    assert CallReceipt.model_validate(response["receipt"]) == CallReceipt.model_validate(original)
    fault.replayed_grants.append(call["operation_id"])
