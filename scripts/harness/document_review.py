"""PG-приёмка границы PDF evidence и неизвестного ACK; без модели и сборки."""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from scripts.harness import runtime as fixture
from service.services.billing.application.frozen_pricing import FrozenPricing
from service.services.chat.application.harness_capability import settings
from service.services.chat.domain.documents.context import document_project_id
from service.services.chat.persistence.harness.admission.document_scope import (
    load_owned_document_scope,
    read_document_scope,
)
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.services.chat.persistence.harness.state import owned_row
from service.shared.harness_protocol import (
    CallReceipt,
    EffectIntent,
    EffectResult,
    Exchange,
    HarnessFailure,
    PaidCall,
)
from service.shared.task_contract import TaskEvidence

STAGE = "source_parity"


async def denied(awaitable, code):
    try:
        await awaitable
    except HarnessFailure as error:
        assert error.code == code
    else:
        raise AssertionError("unsafe_transition_admitted")


async def exercise(engine):
    global STAGE
    owner, admission = await fixture.seed(engine)
    project = document_project_id(owner.user_id, owner.thread_id, "documents/cats")
    owner = owner.model_copy(update={"project_id": project})
    admission = admission.model_copy(
        update={
            "surface": "pdf",
            "actions": ("read", "document"),
            "project_id": project,
        }
    )
    connector = SimpleNamespace(
        get_session_context=async_sessionmaker(engine, expire_on_commit=False)
    )
    repo = HarnessRuntimeRepository(connector)
    tariff = FrozenPricing(
        entries=[],
        classes=[],
        default={"model": "default", "incoming": "0.01", "outgoing": "0.01"},
        credit_unit="0.01",
        margin="1",
        complexity="1",
        minimum=0,
        minimum_margin="1",
        surcharges={"workspace_tool": "0.01"},
    )
    STAGE = "admit_pdf_contract"
    document_context = {
        "path": "documents/cats",
        "expected_revision": "r1",
        "authoring_version": 1,
        "draft_digest": "c" * 64,
        "block_ids": ["intro"],
        "content": "PRIVATE_SOURCE",
        "coordination_capability": "PRIVATE_CAPABILITY",
    }
    await repo.admit(owner, admission, tariff, document_context=document_context)
    STAGE = "frozen_document_scope"
    async with connector.get_session_context() as db:
        row = await owned_row(db, owner)
        stored_scope = await read_document_scope(db, row, owner)
        assert stored_scope["block_ids"] == ["intro"] and "PRIVATE" not in json.dumps(stored_scope)
    assert await load_owned_document_scope(connector, owner) == stored_scope
    await denied(
        repo.admit(
            owner,
            admission,
            tariff,
            document_context={**document_context, "block_ids": []},
        ),
        "operation_conflict",
    )
    STAGE = "reject_other_document_criterion"
    await denied(
        repo.exchange(
            owner,
            Exchange(
                opcode="seal",
                expected_revision=0,
                proposal={
                    "kind": "document",
                    "criteria": [
                        {"criterion_id": "slides", "kind": "pdf", "target": "documents/other"},
                    ],
                },
            ),
        ),
        "task_contract_invalid",
    )
    sealed = await repo.exchange(
        owner,
        Exchange(
            opcode="seal",
            expected_revision=0,
            proposal={
                "kind": "document",
                "criteria": [
                    {"criterion_id": "slides", "kind": "pdf", "target": "documents/cats"},
                ],
            },
        ),
    )
    assert sealed["snapshot"]["state"]["contract"]["kind"] == "document"
    operation = str(uuid4())
    intent = EffectIntent(
        operation_id=operation,
        name="tex_propose_structure",
        action="document",
        source_revision="r1",
        arguments='{"base_version":1,"insertions":[]}',
    )
    await repo.exchange(owner, Exchange(opcode="prepare_effect", effect=intent))
    await repo.exchange(owner, Exchange(opcode="dispatch_effect", operation_id=operation))
    proof = TaskEvidence(
        criterion_id="slides",
        operation_id=operation,
        kind="pdf",
        target="documents/cats",
        source_revision="r1",
        digest="a" * 64,
        outcome="passed",
        artifact_id="invented",
    )
    STAGE = "reject_adapter_pdf_proof"
    await denied(
        repo.exchange(
            owner,
            Exchange(
                opcode="effect_receipt",
                effect_result=EffectResult(
                    operation_id=operation,
                    status="succeeded",
                    text="awaiting_review",
                    evidence=[proof],
                    charged=True,
                ),
            ),
        ),
        "verification_missing",
    )
    receipt = EffectResult(
        operation_id=operation,
        status="succeeded",
        text='{"status":"awaiting_review"}',
        charged=True,
    )
    await repo.exchange(owner, Exchange(opcode="effect_receipt", effect_result=receipt))
    before = await repo.exchange(owner, Exchange(opcode="state"))
    repo = HarnessRuntimeRepository(connector)
    await repo.exchange(owner, Exchange(opcode="effect_receipt", effect_result=receipt))
    assert await repo.exchange(owner, Exchange(opcode="state")) == before
    result = (await repo.exchange(owner, Exchange(opcode="result")))["result"]
    assert result["status"] == "blocked" and result["unchecked"] == ["slides"]
    STAGE = "reject_adapter_source_revision"
    current = before["snapshot"]
    await denied(
        repo.exchange(
            owner,
            Exchange(
                opcode="checkpoint",
                expected_revision=current["revision"],
                state={**current["state"], "source_revision": "not-executor-owned"},
                continuation=current["continuation"],
            ),
        ),
        "binding_changed",
    )
    STAGE = "retain_unknown_proposal_cost"
    unknown = str(uuid4())
    await repo.exchange(
        owner,
        Exchange(
            opcode="prepare_effect",
            effect=intent.model_copy(update={"operation_id": unknown}),
        ),
    )
    fee = PaidCall(
        operation_id=str(uuid4()),
        provider="local",
        model="workspace_tool",
        kind="tool",
        prompt=0,
        completion=0,
        billing_tool="workspace_tool",
        request_digest="f" * 64,
    )
    await repo.exchange(owner, Exchange(opcode="grant", call=fee))
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=fee.operation_id))
    await repo.exchange(owner, Exchange(opcode="dispatch_effect", operation_id=unknown))
    await repo.exchange(
        owner,
        Exchange(
            opcode="effect_receipt",
            effect_result=EffectResult(
                operation_id=unknown,
                status="unknown",
                text="ACK unavailable",
            ),
        ),
    )
    unknown_fee = CallReceipt(operation_id=fee.operation_id, status="unknown")
    await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=unknown_fee))
    pending = await repo.exchange(owner, Exchange(opcode="state"))
    assert pending["snapshot"]["held_credits"] > 0
    await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=unknown_fee))
    assert await repo.exchange(owner, Exchange(opcode="state")) == pending
    result = (await repo.exchange(owner, Exchange(opcode="result")))["result"]
    assert result["status"] != "completed" and result["blocker"] == "cost_unknown"
    await denied(
        repo.exchange(
            owner,
            Exchange(
                opcode="prepare_effect",
                effect=intent.model_copy(update={"operation_id": str(uuid4())}),
            ),
        ),
        "operation_unknown",
    )
    return [
        "original_document_scope_durable",
        "changed_document_selection_rejected",
        "other_document_criterion_rejected",
        "proposal_cannot_attest_pdf",
        "duplicate_receipt_unchanged",
        "pdf_revision_requires_executor",
        "unknown_ack_retains_cost_and_blocks_effect",
    ]


async def main():
    files = json.load(sys.stdin)["files"]
    assert all(
        hashlib.sha256(
            (Path(__file__).resolve().parents[1] / path.removeprefix("scripts/")).read_bytes()
            if path.startswith("scripts/")
            else Path(path).read_bytes()
        ).hexdigest()
        == digest
        for path, digest in files.items()
    )
    os.environ["HARNESS__PDF_ENABLED"] = "true"
    settings.cache_clear()
    async with fixture.disposable() as engine, asyncio.timeout(40):
        cases = await exercise(engine)
    print(json.dumps({"cases": cases, "fixture_removed": True, "source_parity": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print(json.dumps({"failed_stage": STAGE}))
        raise SystemExit(1) from None
