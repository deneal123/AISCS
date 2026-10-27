"""Legacy orchestration units model an empty audit table, not real SQL sessions.

Dedicated reconciliation/SQL tests supply started attempts explicitly.
"""

from unittest.mock import AsyncMock

import pytest

from service.services.chat.application.documents.audit import (
    reconciliation as document_audit_reconciliation,
)


@pytest.fixture(autouse=True)
def no_started_audit_rows(monkeypatch):
    monkeypatch.setattr(document_audit_reconciliation, "started_id", AsyncMock(return_value=None))
