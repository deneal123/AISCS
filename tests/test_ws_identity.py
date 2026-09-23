"""WS-чат обязан брать личность ТОЛЬКО из аутентифицированной сессии.

Регрессия аудита (T1.1): `ws_message_use_case` брал `msg.get("user_id") or
session.get("user_id")` — тело клиента перекрывало сессию, и аутентифицированный A,
прислав `user_id` жертвы B, создавал джоб и списание НА B. HTTP-путь всегда форсит
user_id из check_auth; приводим WS к тому же контракту.
"""

import pytest

from service.services.chat.application.use_cases.ws_message_use_case import (
    HandleWsChatMessageUseCase,
)

ATTACKER = "11111111-1111-1111-1111-111111111111"
VICTIM = "22222222-2222-2222-2222-222222222222"


class _JobResp:
    job_id = "job-1"


class _Queue:
    def __init__(self, sink):
        self._sink = sink

    def enqueue_agent_message(self, **kw):
        self._sink["enqueue_user_id"] = kw.get("user_id")
        return "task-1"


class _JobService:
    def __init__(self, sink):
        self.sink = sink
        self.job_queue = _Queue(sink)

    async def create_chat_job(self, user_id, thread_id, text):
        self.sink["job_user_id"] = str(user_id)
        return _JobResp()

    async def update_job_celery_task_id(self, job_id, task_id):
        return None


async def _run(msg, session):
    sink: dict = {}
    uc = HandleWsChatMessageUseCase(job_service=_JobService(sink), chat_service=object())
    await uc.execute(thread_id="t", msg=msg, session=session)
    return sink


@pytest.mark.asyncio
async def test_ws_ignores_spoofed_user_id_in_body():
    """Подставленный в тело чужой user_id ДОЛЖЕН быть проигнорирован."""
    sink = await _run(msg={"text": "hi", "user_id": VICTIM}, session={"user_id": ATTACKER})
    assert sink["job_user_id"] == ATTACKER, "джоб создан под личностью из ТЕЛА, а не сессии"
    assert sink["enqueue_user_id"] == ATTACKER, "биллинг ушёл на чужого user_id"


@pytest.mark.asyncio
async def test_ws_ignores_anonymous_spoof():
    """all-zeros в теле не должен уводить траты на общий аноним-кошелёк."""
    sink = await _run(
        msg={"text": "hi", "user_id": "00000000-0000-0000-0000-000000000000"},
        session={"user_id": ATTACKER},
    )
    assert sink["job_user_id"] == ATTACKER


@pytest.mark.asyncio
async def test_ws_uses_session_identity_normally():
    """Без подставного поля — обычная работа: личность из сессии."""
    sink = await _run(msg={"text": "hi"}, session={"user_id": ATTACKER})
    assert sink["job_user_id"] == ATTACKER
