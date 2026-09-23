"""Фаза 1 биллинга: ЗАПИСЬ потребления токенов.

Всё, что было до этой точки в цепочке (client → base._extract_usage → ReplyAssembler →
execution_result), уехало в сайдкар: ``agents/tests/cross_service/test_billing_usage.py``.
Там движок доказывает, что отдаёт правильные числа, — здесь backend доказывает, что
правильно их записывает. Это последнее звено, и оно чисто backend'овое: SQL-текст
INSERT'а и коммит от ``@connection()``.
"""

import json

import pytest

from service.services.billing.persistence.billing_repository import BillingRepository
from tests.test_helpers import FakeConnector, FakeDBSession


@pytest.mark.asyncio
async def test_billing_repository_records_usage_event() -> None:
    session = FakeDBSession()
    repo = BillingRepository(FakeConnector(session))

    await repo.record_usage_event(
        user_id="11111111-1111-1111-1111-111111111111",
        tokens=150,
        metadata={"prompt": 120, "completion": 30, "model": "m"},
    )

    assert len(session.executed) == 1
    sql, params = session.executed[0]
    assert "INSERT INTO profile.billing_events" in sql
    assert params["event_type"] == "usage"
    assert params["tokens"] == 150
    assert params["user_id"] == "11111111-1111-1111-1111-111111111111"
    assert json.loads(params["metadata"]) == {"prompt": 120, "completion": 30, "model": "m"}
    # @connection() должен закоммитить
    assert session._committed is True
