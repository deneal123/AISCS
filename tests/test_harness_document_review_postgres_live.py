"""Отдельная PG-БД: proposal не PDF, неизвестный ACK не нулевой расход."""

import os

import pytest

from tests.harness_postgres import run_probe


@pytest.mark.skipif(os.getenv("HARNESS_RUNTIME_LIVE") != "1", reason="disposable runtime PG opt-in")
def test_pdf_review_receipt_authority_and_unknown_cost_on_postgres():
    assert run_probe(
        "document_review",
        [
            "service/shared/harness_protocol.py",
            "service/shared/task_contract.py",
            "service/services/chat/persistence/harness/effects.py",
            "service/services/chat/persistence/harness/runtime.py",
            "service/services/chat/persistence/harness/state.py",
            "service/services/chat/persistence/harness/admission/document_scope.py",
            "service/services/chat/persistence/harness/admission/sealing.py",
        ],
    ) == {
        "cases": [
            "original_document_scope_durable",
            "changed_document_selection_rejected",
            "other_document_criterion_rejected",
            "proposal_cannot_attest_pdf",
            "duplicate_receipt_unchanged",
            "pdf_revision_requires_executor",
            "unknown_ack_retains_cost_and_blocks_effect",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
