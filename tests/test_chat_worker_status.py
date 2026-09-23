"""Воркер чата: FAILURE-статус упавшего job фиксируется в отдельной транзакции.

Регрессия: раньше FAILURE писался в уже ``rollback()``-нутую worker-сессию и не
коммитился (``@connection`` при переданной сессии коммитит свою throwaway-сессию,
а не нашу) — упавший job навсегда оставался ``PROCESSING``: ветка идемпотентности
«already FAILURE» была мертва, а ``task_acks_late``-редоставка гоняла пайплайн
заново. ``_mark_job_failed_committed`` пишет статус на СВЕЖЕЙ сессии и коммитит сам.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker import message_meta
from service.services.chat.infrastructure.chat_worker_tasks import (
    _mark_job_failed_committed,
    _persist_partial_turn_committed,
)
from tests.test_helpers import FakeConnector, FakeDBSession


class _FakeJobRepo:
    def __init__(self):
        self.updated_status = None

    async def fetch_job_by_id(self, job_uuid, user_uuid, session=None):
        return SimpleNamespace(
            id=job_uuid,
            user_id=user_uuid,
            type="chat",
            status=ProcessingStatus.PROCESSING,
            created_at=None,
            updated_at=None,
            payload={},
        )

    async def update_job_status(self, job, session=None):
        self.updated_status = job.status


@pytest.mark.asyncio
async def test_mark_job_failed_commits_on_fresh_session() -> None:
    session = FakeDBSession()
    job_repo = _FakeJobRepo()

    await _mark_job_failed_committed(FakeConnector(session), job_repo, str(uuid4()), str(uuid4()))

    assert job_repo.updated_status == ProcessingStatus.FAILURE
    assert session._committed is True  # статус реально закоммичен (не потерян)


@pytest.mark.asyncio
async def test_mark_job_failed_is_best_effort_when_job_missing() -> None:
    # Job не найден -> статус не трогаем, но и НЕ падаем (не маскируем исходную ошибку).
    class _MissingJobRepo(_FakeJobRepo):
        async def fetch_job_by_id(self, job_uuid, user_uuid, session=None):
            return None

    session = FakeDBSession()
    await _mark_job_failed_committed(FakeConnector(session), _MissingJobRepo(), str(uuid4()), None)

    assert session._committed is True  # свежая транзакция закрыта штатно


@pytest.mark.asyncio
async def test_persist_partial_turn_commits_on_fresh_session() -> None:
    # Обрыв стрима после отданных токенов → частичный ответ сохраняется (иначе в
    # истории пусто, хотя пользователь видел текст).
    session = FakeDBSession(first_map={"SELECT id FROM profile.chat_threads": (123,)})
    uid = "11111111-1111-1111-1111-111111111111"

    await _persist_partial_turn_committed(
        FakeConnector(session), "thread-1", "вопрос", "частичный ответ", uid
    )

    inserts = [s for s, _ in session.executed if "INSERT INTO profile.chat_messages" in s]
    assert len(inserts) == 2  # user + assistant (частичный)
    assert session._committed is True


@pytest.mark.asyncio
async def test_persist_partial_turn_noop_for_empty_partial() -> None:
    session = FakeDBSession()
    await _persist_partial_turn_committed(FakeConnector(session), "thread-1", "вопрос", "   ", "u")
    assert session.executed == []  # пустой частичный ответ не сохраняем
    assert session._committed is False


# --------------------------------------------------------------------------- #
# _redelivery_short_circuit — гейт идемпотентности против редоставки Celery    #
# --------------------------------------------------------------------------- #
def _repo_returning(job):
    class _Repo:
        async def fetch_job_by_id(self, job_uuid, user_uuid, session=None):
            return job

    return _Repo()


@pytest.mark.asyncio
async def test_redelivery_short_circuit_skips_completed_job() -> None:
    import service.services.chat.infrastructure.chat_worker_tasks as cwt

    job = SimpleNamespace(
        status=ProcessingStatus.SUCCESS,
        payload={"reply": "hi", "file_url": None, "metadata": {"a": 1}},
    )
    res = await cwt._redelivery_short_circuit(
        _repo_returning(job), str(uuid4()), FakeDBSession(), str(uuid4())
    )
    assert res is not None
    assert res["status"] == "success"
    assert res["reply"] == "hi"
    assert res["metadata"] == {"a": 1}


@pytest.mark.asyncio
async def test_redelivery_short_circuit_skips_failed_job() -> None:
    import service.services.chat.infrastructure.chat_worker_tasks as cwt

    job = SimpleNamespace(status=ProcessingStatus.FAILURE, payload=None)
    res = await cwt._redelivery_short_circuit(
        _repo_returning(job), str(uuid4()), FakeDBSession(), str(uuid4())
    )
    assert res == {"status": "error", "error": "Job already failed"}


@pytest.mark.asyncio
async def test_redelivery_short_circuit_none_for_fresh_job() -> None:
    import service.services.chat.infrastructure.chat_worker_tasks as cwt

    res = await cwt._redelivery_short_circuit(
        _repo_returning(None), str(uuid4()), FakeDBSession(), str(uuid4())
    )
    assert res is None  # свежий job — гоним пайплайн


# --------------------------------------------------------------------------- #
# _build_public_usage_meta — безопасный whitelist usage для клиента            #
# --------------------------------------------------------------------------- #
def test_build_public_usage_meta_none_when_no_tokens() -> None:

    assert (
        message_meta.build_public_usage_meta({"total_tokens": 0}, charged_credits=5, model="m")
        is None
    )


def test_build_public_usage_meta_includes_credits_and_model() -> None:

    meta = message_meta.build_public_usage_meta(
        {"total_tokens": 30, "prompt_tokens": 10, "completion_tokens": 20},
        charged_credits=7,
        model="gpt-4o",
    )
    assert meta == {"prompt": 10, "completion": 20, "total": 30, "model": "gpt-4o", "credits": 7}


def test_build_public_usage_meta_omits_credits_when_zero() -> None:

    meta = message_meta.build_public_usage_meta({"total_tokens": 30}, charged_credits=0, model="m")
    assert meta is not None
    assert "credits" not in meta  # нечего показывать — поле не отдаём
    assert meta["total"] == 30


# --------------------------------------------------------------------------- #
# _handle_worker_failure — единая очистка после падения/отмены                 #
# --------------------------------------------------------------------------- #
class _Pub:
    def __init__(self):
        self.published: list = []

    def publish_payload(self, payload):
        self.published.append(payload)


@pytest.mark.asyncio
async def test_handle_worker_failure_releases_and_persists_partial(monkeypatch) -> None:
    import service.services.chat.infrastructure.chat_worker_tasks as cwt

    calls: dict = {}

    async def _release(**kw):
        calls["released"] = kw["reservation_id"]

    async def _fail(pg, repo, jid, uid):
        calls["failed"] = jid

    async def _partial(pg, tid, utext, atext, uid, meta=None):
        calls["partial"] = atext
        calls["meta"] = meta

    monkeypatch.setattr(cwt, "_release_reservation", _release)
    monkeypatch.setattr(cwt, "_mark_job_failed_committed", _fail)
    monkeypatch.setattr(cwt, "_persist_partial_turn_committed", _partial)

    pub = _Pub()
    await cwt._handle_worker_failure(
        pg_connector=object(),
        config=object(),
        job_repo=object(),
        publisher=pub,
        exc=RuntimeError("boom"),
        job_id="j1",
        thread_id="t1",
        user_text="вопрос",
        user_id="u1",
        reservation_id="r1",
        charged_credits=0,
        streamed_parts=["Hel", "lo"],
        attachments=[{"name": "tz.pdf", "kind": "document"}],
    )

    assert calls["released"] == "r1"  # не списывали → резерв отпущен
    assert calls["failed"] == "j1"  # FAILURE зафиксирован
    assert "Hello" in calls["partial"] and "прервана" in calls["partial"]
    # 🔴 Аварийный путь тоже пишет ВЛОЖЕНИЯ: без них приложенный файл виден до F5
    # (стейт фронта) и исчезает после (в БД пусто).
    assert calls["meta"] == {"attachments": [{"filename": "tz.pdf", "file_type": "document"}]}
    assert pub.published  # ошибка опубликована клиенту


@pytest.mark.asyncio
async def test_handle_worker_failure_refunds_when_already_charged(monkeypatch) -> None:
    import service.services.billing.application.billing_service as bs_mod
    import service.services.chat.infrastructure.chat_worker_tasks as cwt

    calls: dict = {"released": False}

    class _FakeBilling:
        def __init__(self, *a, **k):
            pass

        async def refund(self, user_id, credits, reason):
            calls["refund"] = (user_id, credits, reason)

    async def _release(**kw):
        calls["released"] = True

    async def _fail(pg, repo, jid, uid):
        pass

    monkeypatch.setattr(cwt, "_overlay_billing", lambda pg, cfg: object())
    monkeypatch.setattr(bs_mod, "BillingService", _FakeBilling)
    monkeypatch.setattr(cwt, "_release_reservation", _release)
    monkeypatch.setattr(cwt, "_mark_job_failed_committed", _fail)

    await cwt._handle_worker_failure(
        pg_connector=object(),
        config=object(),
        job_repo=object(),
        publisher=_Pub(),
        exc=RuntimeError("boom"),
        job_id="j1",
        thread_id="t1",
        user_text="вопрос",
        user_id="u1",
        reservation_id="r1",
        charged_credits=42,
        streamed_parts=[],  # ничего не стримили → партиал не сохраняем
    )

    assert calls["refund"] == ("u1", 42, "job_failed_after_charge")
    assert calls["released"] is False  # при refund резерв повторно не отпускаем
