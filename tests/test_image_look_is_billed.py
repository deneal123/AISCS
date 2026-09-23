"""Взгляд VLM на картинку оплачивает пользователь, а не платформа.

🔴 ЗАМЕРЕНО ПО ИСТОРИЧЕСКИМ ДАННЫМ. В базе 13 загруженных картинок и НОЛЬ событий
биллинга за них:

    kind          | count
    --------------+------
    (обычный ход) |  730
    graph_index   |   47
    transcription |   20

Описание картинки — ОТДЕЛЬНЫЙ вызов VLM на загрузке: он идёт до всякого хода диалога, и
его токены не попадают ни в один `_charge_usage`. Ручка сайдкара при этом отдавала один
текст, выбрасывая `usage`, — тот же способ потерять деньги, что уже был у провайдерского
STT («resp.usage в сайдкаре выбрасывался, эндпоинт отдавал только текст»).

⚠️ Цена — по РЕАЛЬНЫМ токенам из общей таблицы моделей, а не отдельной ставкой: зрячие
модели различаются в цене на порядки, и фиксированная плата была бы либо подарком на
дорогой, либо грабежом на дешёвой.
"""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

from service.services.chat.presentation.http import upload_api


class _Redis:
    """Двойник Redis для маркера дедупа: помнит занятые ключи."""

    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def set(self, key, value, nx=False, ex=None):  # noqa: A002
        if nx and key in self.claimed:
            return None
        self.claimed.add(key)
        return True

    async def delete(self, key):
        self.claimed.discard(key)
        return 1


@pytest.fixture
def charged(monkeypatch):
    """Перехватывает списание: что именно ушло в биллинг."""
    seen: list[dict] = []

    async def _charge(**kw):
        seen.append(kw)
        return 42

    monkeypatch.setattr(
        "service.services.chat.infrastructure.chat_worker.charging._charge_usage", _charge
    )
    monkeypatch.setattr(
        "service.services.chat.infrastructure.chat_worker.factory."
        "ChatWorkerDependencyFactory.create_pg_connector",
        lambda self, cfg: object(),
    )
    return seen


USAGE = {"model": "openai/gpt-4o", "prompt": 1200, "completion": 80, "total": 1280}


@pytest.mark.asyncio
async def test_a_look_at_pixels_is_charged(charged):
    """🔴 ГЛАВНОЕ: usage взгляда доходит до списания вместе с моделью."""
    await upload_api._charge_image_usage(object(), _Redis(), "u-1", "hash-1", USAGE)

    assert charged, "картинка снова описана бесплатно — платит платформа"
    call = charged[0]
    assert call["resolved_model"] == "openai/gpt-4o", "модель потеряна — цена станет дефолтной"
    per_call = call["execution_result"]["per_call_usage"][0]
    assert (per_call["prompt"], per_call["completion"]) == (1200, 80)


@pytest.mark.asyncio
async def test_a_refused_look_costs_nothing(charged):
    """🔴 ГРАНИЦА, И ОНА ИЗ СЕГОДНЯШНЕГО ЖЕ ПРАВИЛА: услуги не было — платы нет. Замер на
    живом стеке: ключ провайдера исчерпан, зрение вернуло «рассмотреть НЕ УДАЛОСЬ»."""
    for empty in (None, {}, {"total": 0}, "не словарь"):
        await upload_api._charge_image_usage(object(), _Redis(), "u-1", "hash-1", empty)

    assert not charged


@pytest.mark.asyncio
async def test_the_same_upload_is_not_charged_twice(charged):
    """⚠️ Дабл-сабмит и ретрай одной загрузки — одна услуга. Дедуп по хэшу файла, как у
    транскрипции."""
    redis = _Redis()

    await upload_api._charge_image_usage(object(), redis, "u-1", "hash-1", USAGE)
    await upload_api._charge_image_usage(object(), redis, "u-1", "hash-1", USAGE)

    assert len(charged) == 1, "повторная загрузка того же файла списана дважды"


@pytest.mark.asyncio
async def test_a_different_file_is_charged_separately(charged):
    """🔴 ГРАНИЦА ДЕДУПА: другой файл — другая работа, и она платная."""
    redis = _Redis()

    await upload_api._charge_image_usage(object(), redis, "u-1", "hash-1", USAGE)
    await upload_api._charge_image_usage(object(), redis, "u-1", "hash-2", USAGE)

    assert len(charged) == 2


@pytest.mark.asyncio
async def test_the_dedup_marker_is_released_when_charging_fails(monkeypatch):
    """🔴 ИНАЧЕ ОШИБКА СПИСАНИЯ ДЕЛАЕТ КАРТИНКУ БЕСПЛАТНОЙ НАВСЕГДА: маркер занят, повтор
    считает себя дублем и молча пропускает плату."""

    async def _boom(**kw):
        raise RuntimeError("биллинг недоступен")

    monkeypatch.setattr(
        "service.services.chat.infrastructure.chat_worker.charging._charge_usage", _boom
    )
    monkeypatch.setattr(
        "service.services.chat.infrastructure.chat_worker.factory."
        "ChatWorkerDependencyFactory.create_pg_connector",
        lambda self, cfg: object(),
    )
    redis = _Redis()

    await upload_api._charge_image_usage(object(), redis, "u-1", "hash-1", USAGE)

    assert not redis.claimed, "маркер дедупа остался занят — повтор уже никогда не спишется"


# --- путь usage от сайдкара до ручки ------------------------------------------------------ #


@pytest.mark.asyncio
async def test_the_adapter_keeps_the_usage_of_a_successful_look(monkeypatch):
    """🔴 ТОЧКА ВЫЗОВА. Ручка сайдкара теперь отдаёт `usage`, но если адаптер его не
    подберёт — тарифицировать снова будет нечего."""
    from service.services.chat.infrastructure.media import openai_media_analysis_adapter as ada

    async def _sidecar(path, payload, *, meta_out=None):
        if meta_out is not None:
            meta_out.update({"text": "описание", "usage": USAGE})
        return "описание"

    monkeypatch.setattr(ada, "_sidecar_media", _sidecar)
    adapter = ada.OpenAIMediaAnalysisAdapter()

    text = await adapter.analyze_image(b"png", "image/png", "pic.png")

    assert "описание" in text
    assert adapter.last_image_usage == USAGE, "usage взгляда потерян в адаптере"


@pytest.mark.asyncio
async def test_a_failed_look_leaves_no_usage(monkeypatch):
    """🔴 ГРАНИЦА. Сайдкар не ответил — заглушка вместо описания, и метки быть не должно:
    иначе платформа выставит счёт за несостоявшийся взгляд."""
    from service.services.chat.infrastructure.media import openai_media_analysis_adapter as ada

    async def _sidecar(path, payload, *, meta_out=None):
        return None

    monkeypatch.setattr(ada, "_sidecar_media", _sidecar)
    adapter = ada.OpenAIMediaAnalysisAdapter()

    text = await adapter.analyze_image(b"png", "image/png", "pic.png")

    assert "НЕ УДАЛОСЬ" in text
    assert adapter.last_image_usage is None


@pytest.mark.asyncio
async def test_the_usage_of_a_previous_image_does_not_leak(monkeypatch):
    """⚠️ Адаптер переиспользуется между загрузками: без сброса метки чужой usage ушёл бы
    в счёт следующего файла. Ровно та же причина, что у транскрипции."""
    from service.services.chat.infrastructure.media import openai_media_analysis_adapter as ada

    calls = {"n": 0}

    async def _sidecar(path, payload, *, meta_out=None):
        calls["n"] += 1
        if calls["n"] == 1 and meta_out is not None:
            meta_out.update({"text": "описание", "usage": USAGE})
            return "описание"
        return None

    monkeypatch.setattr(ada, "_sidecar_media", _sidecar)
    adapter = ada.OpenAIMediaAnalysisAdapter()

    await adapter.analyze_image(b"png", "image/png", "first.png")
    await adapter.analyze_image(b"png", "image/png", "second.png")

    assert adapter.last_image_usage is None, "usage прошлой картинки ушёл бы в чужой счёт"


def test_the_endpoint_charges_the_look():
    """🔴 ВТОРАЯ ТОЧКА ВЫЗОВА. Правило верно, но если ручка его не зовёт — оно мертво.
    Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым правка объяснена."""

    tree = ast.parse(inspect.getsource(upload_api.upload_file_to_chat).strip())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_charge_image_usage"
    ]

    assert calls, "ручка не тарифицирует взгляд — картинки снова описываются за наш счёт"


@pytest.mark.asyncio
async def test_the_use_case_passes_the_usage_to_the_endpoint(monkeypatch):
    """🔴 СРЕДНЕЕ ЗВЕНО, И МУТАЦИЯ ПОКАЗАЛА, ЧТО ОНО НЕ СТЕРЕГЛОСЬ. Адаптер usage
    подбирает, ручка его тарифицирует — но между ними use case, который обязан положить
    метку в результат. Убери оттуда одну строку, и всё остальное останется верным, а
    картинки снова станут бесплатными.
    """
    from service.services.chat.application.use_cases.upload_file_use_case import UploadFileUseCase

    class _Port:
        last_transcription = None
        last_image_usage = dict(USAGE)

        async def analyze_image(self, *a, **kw):
            return "[описание картинки]"

    class _Files:
        async def save(self, **kw):
            return SimpleNamespace(
                file_id="opaque-file-id",
                file_url="internal://stored",
                file_key="CHAT/opaque-file-id.png",
            )

    use_case = UploadFileUseCase(
        media_analysis_port=_Port(), file_service=_Files(), graph_client=None
    )

    result = await use_case.execute(
        filename="pic.png",
        content_type="image/png",
        content_bytes=b"\x89PNG",
        thread_id="t-1",
        user_id="u-1",
    )

    assert result.get("image_usage") == USAGE, (
        "usage взгляда не доезжает до ручки — тарифицировать будет нечего"
    )
