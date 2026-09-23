"""Дедуп списания транскрибации (аудит T2.4).

Раньше `charge` за локальную транскрибацию шёл без идемпотентности — дабл-сабмит/ретрай
одной загрузки списывал дважды. Окно дедупа (Redis SET NX EX) гасит быстрые дубли по хэшу
содержимого, не трогая легитимную пере-транскрибацию позже.
"""

import pytest

from service.services.chat.presentation.http import upload_api as ua


class _FakeRedis:
    """Минимальный async-Redis: set(nx, ex) + delete, как настоящий."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None  # уже есть → NX не срабатывает
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.mark.asyncio
async def test_double_submit_is_deduped():
    r = _FakeRedis()
    first = await ua._claim_transcription_charge(r, "u1", "hashA")
    second = await ua._claim_transcription_charge(r, "u1", "hashA")
    assert first is True, "первый сабмит должен списывать"
    assert second is False, "дабл-сабмит той же загрузки должен пропускаться (дедуп)"


@pytest.mark.asyncio
async def test_different_files_not_deduped():
    r = _FakeRedis()
    assert await ua._claim_transcription_charge(r, "u1", "hashA") is True
    other = await ua._claim_transcription_charge(r, "u1", "hashB")
    assert other is True, "другой файл — своё списание"


@pytest.mark.asyncio
async def test_release_allows_recharge_on_failure():
    """Если списание упало — маркер снимается, ретрай в окне может списать."""
    r = _FakeRedis()
    assert await ua._claim_transcription_charge(r, "u1", "hashA") is True
    await ua._release_transcription_charge(r, "u1", "hashA")
    assert await ua._claim_transcription_charge(r, "u1", "hashA") is True


@pytest.mark.asyncio
async def test_fail_open_without_redis():
    """redis=None → всегда списываем: сбой дедупа не должен ПРОПУСКАТЬ легитимное списание."""
    assert await ua._claim_transcription_charge(None, "u1", "hashA") is True


@pytest.mark.asyncio
async def test_fail_open_on_redis_error():
    class _Boom:
        async def set(self, *a, **k):
            raise RuntimeError("redis down")

    assert await ua._claim_transcription_charge(_Boom(), "u1", "hashA") is True
