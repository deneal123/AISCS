"""Два извлечения контракта на окно информации, без сброса общего бюджета задания."""

import json

from service.shared.task_contract import canonical_uuid, digest_payload

SERVER_JOB = "_admission_job_v1"


def contract_request(raw):
    if raw.get("kind") != "meta_usage" or raw.get("billing_tool"):
        return False
    encoded = raw.get("canonical_request")
    if encoded is None:
        return True  # Старые meta receipts без запроса учитываются консервативно.
    try:
        body = json.loads(encoded)
        functions = body.get("functions") or [
            tool.get("function", {}) for tool in body.get("tools", [])
        ]
        return any(function.get("name") == "submit_task_contract" for function in functions)
    except (ValueError, TypeError, AttributeError):
        return True  # В production невалидное тело раньше отсекает frozen-request gate.


def precontract_limit_reached(row, call, grants):
    raw = {
        "kind": call.kind,
        "billing_tool": getattr(call, "billing_tool", None),
        "canonical_request": getattr(call, "canonical_request", None),
    }
    if row["checkpoint"] is not None or not contract_request(raw):
        return False
    root = str(row.get("task_id"))
    active = str(row.get("active_job_id", root))
    return (
        sum(
            contract_request(grant["request"]) and grant["request"].get(SERVER_JOB, root) == active
            for grant in grants
        )
        >= 2
    )


def stored_call(row, call):
    raw = call.model_dump(mode="json")
    if row["checkpoint"] is None and contract_request(raw):
        # Job берётся только из fenced owning row. Client не присылает epoch,
        # а новый attempt того же job не может обнулить это окно.
        raw[SERVER_JOB] = canonical_uuid(str(row["active_job_id"]))
    return raw


def wire_call(raw):
    detached = dict(raw)
    if SERVER_JOB in detached:
        canonical_uuid(detached.pop(SERVER_JOB))
    return detached


def verified_wire_call(raw, stored_digest):
    detached = wire_call(raw)
    if stored_digest not in {digest_payload(raw), digest_payload(detached)}:
        raise ValueError("grant_request_digest_invalid")
    return detached
