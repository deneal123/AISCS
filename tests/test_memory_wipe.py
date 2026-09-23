"""Полная очистка долговременной памяти по кнопке пользователя.

Удалять факты можно было по одному, а стереть всё — нельзя. При десятках записей это
превращается в занятие, а не в операцию, и «забудь про меня» становится недостижимым.

🔴 Память живёт в ДВУХ хранилищах: реестр фактов в Postgres (то, что видно списком) и
семантическая память MemOS (из неё в промпт подмешиваются похожие прошлые обсуждения).
Очистить только первое — оставить человека с ассистентом, который «всё ещё помнит» при
пустом списке. Объяснить это ему нечем.

⚠️ Отчёт РАЗДЕЛЬНЫЙ. Провайдер памяти бывает выключен или лежит; тогда факты стёрты, а
MemOS нет, и общий «ок» был бы прямым обманом того, кто нажал кнопку.
"""

from __future__ import annotations

import json

import httpx
import pytest

from service.infrastructure.memory.memos import MemOSMemoryIntegration
from service.services.analytics.application import memory_cache
from service.services.analytics.application.memory_service import MemoryService


class _FakeRepo:
    def __init__(self, count: int = 3, boom: bool = False):
        self.count = count
        self.boom = boom
        self.calls: list[str] = []

    async def delete_all_facts(self, *, user_id: str) -> int:
        if self.boom:
            raise RuntimeError("postgres недоступен")
        self.calls.append(user_id)
        return self.count


class _FakeMemos:
    available = True

    def __init__(self, result=None, boom: bool = False):
        self.calls: list[str] = []
        self.boom = boom
        self._result = result if result is not None else {"ok": True, "neo4j_deleted": 7}

    async def forget_user(self, *, user_id: str):
        if self.boom:
            raise RuntimeError("memos лежит")
        self.calls.append(user_id)
        return self._result

    async def dashboard(self, *, user_id: str):
        return {"text": 1}


class _ProviderWithoutWipe:
    """Провайдер без сброса (noop/mem0): метода `forget_user` у него просто нет."""

    available = True


@pytest.fixture()
def redis(monkeypatch):
    """⚠️ Патчим ТАМ, ГДЕ ЧИТАЮТ — в модуле кэша, а не в сервисе."""
    calls: list[str] = []

    async def _invalidate(scoped_user_id: str) -> None:
        calls.append(scoped_user_id)

    monkeypatch.setattr(memory_cache, "invalidate", _invalidate)
    return calls


@pytest.mark.asyncio
async def test_wipes_both_stores(redis):
    """🔴 ГЛАВНОЕ: стираются и факты, и семантическая память."""
    repo, memos = _FakeRepo(count=34), _FakeMemos()
    svc = MemoryService(integration=memos, facts_repo=repo)

    report = await svc.forget_everything("u1")

    assert repo.calls, "факты не стёрты"
    assert memos.calls, "семантическая память MemOS осталась нетронутой"
    assert report["facts_deleted"] == 34
    assert report["memos"]["ok"] is True


@pytest.mark.asyncio
async def test_both_stores_get_the_same_scoped_user(redis):
    """Скоуп один на оба хранилища: иначе стёрлось бы у одного, осталось у другого."""
    repo, memos = _FakeRepo(), _FakeMemos()

    await MemoryService(integration=memos, facts_repo=repo).forget_everything("u1")

    assert repo.calls == ["user:u1"] == memos.calls


@pytest.mark.asyncio
async def test_memos_failure_is_reported_not_swallowed(redis):
    """🔴 MemOS упал — так и говорим. «Готово» при уцелевшей памяти — обман."""
    repo = _FakeRepo(count=5)
    svc = MemoryService(integration=_FakeMemos(boom=True), facts_repo=repo)

    report = await svc.forget_everything("u1")

    assert report["facts_deleted"] == 5, "видимую половину надо было стереть в любом случае"
    assert report["memos"]["ok"] is False, "сбой MemOS выдан за успех"


@pytest.mark.asyncio
async def test_provider_without_wipe_is_reported(redis):
    """Провайдер без сброса — не ошибка, но и не успех: сообщаем причину."""
    svc = MemoryService(integration=_ProviderWithoutWipe(), facts_repo=_FakeRepo())

    report = await svc.forget_everything("u1")

    assert report["facts_deleted"] == 3
    assert report["memos"] == {"ok": False, "reason": "provider_has_no_wipe"}


@pytest.mark.asyncio
async def test_facts_failure_does_not_stop_the_memos_wipe(redis):
    """Половины независимы: падение Postgres не должно оставлять MemOS полным."""
    memos = _FakeMemos()
    svc = MemoryService(integration=memos, facts_repo=_FakeRepo(boom=True))

    report = await svc.forget_everything("u1")

    assert memos.calls, "MemOS не стёрли из-за сбоя в другом хранилище"
    assert report["facts_error"], "сбой по фактам не попал в отчёт"


@pytest.mark.asyncio
async def test_dashboard_cache_is_dropped(redis):
    """🔴 Кэш дашборда живёт 5 минут — без сброса панель покажет счётчики СТЁРТОЙ памяти.

    Со стороны это «кнопка не сработала»: список пуст, а «MemOS · 12 записей» на месте.
    """
    await MemoryService(integration=_FakeMemos(), facts_repo=_FakeRepo()).forget_everything("u1")

    assert redis == ["user:u1"], "кэш дашборда не сброшен после очистки"


@pytest.mark.asyncio
async def test_empty_user_wipes_nothing(redis):
    """Пустой идентификатор — не «все пользователи», а отказ."""
    repo, memos = _FakeRepo(), _FakeMemos()

    report = await MemoryService(integration=memos, facts_repo=repo).forget_everything("")

    assert repo.calls == [] and memos.calls == []
    assert report["facts_deleted"] == 0


# --------------------------------------------------------------------------- #
# Адаптер MemOS                                                                #
# --------------------------------------------------------------------------- #
def _adapter(handler):
    return MemOSMemoryIntegration(
        base_url="http://memos.local",
        api_key="secret",
        transport=httpx.MockTransport(handler),
        mem_cube_template="gpthub-{user_id}",
    )


@pytest.mark.asyncio
async def test_forget_user_hits_the_per_user_endpoint_scoped_by_cube():
    """🔴 Сброс идёт по КУБУ пользователя, а не по общему `/admin/wipe` (это все сразу)."""
    captured: dict = {}

    def _h(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": {"neo4j_deleted": 4, "vectors_deleted": 4}})

    result = await _adapter(_h).forget_user(user_id="user:42")

    assert captured["path"] == "/product/admin/wipe_user"
    assert captured["body"] == {"user_name": "gpthub-user:42"}
    # ⚠️ Заголовок обязателен: две прежние копии вызова wipe ходили БЕЗ него, и дефект
    # был латентным ровно до дня, когда зададут AGENTS__MEMOS_API_KEY.
    assert captured["auth"] == "Bearer secret"
    assert result == {"ok": True, "neo4j_deleted": 4, "vectors_deleted": 4}


@pytest.mark.asyncio
async def test_forget_user_reports_http_failure():
    """Ответ ЯВНЫЙ, а не fail-open None: «стёрли» и «не смогли» путать нельзя."""

    def _h(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    assert (await _adapter(_h).forget_user(user_id="user:42"))["ok"] is False


@pytest.mark.asyncio
async def test_forget_user_without_memos_configured():
    integration = MemOSMemoryIntegration(base_url="")

    assert (await integration.forget_user(user_id="user:42"))["ok"] is False
