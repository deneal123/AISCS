"""Описание картинок и провайдерский STT через сайдкар agents.

⚠️ У этого адаптера НЕ БЫЛО НИ ОДНОГО ТЕСТА, при том что он единственный путь, которым
загруженная картинка превращается в текст для модели. Отказ здесь не роняет загрузку —
пользователь получает заглушку «файл приложен», — и именно поэтому поломка тут ТИХАЯ:
внешне всё работает, просто ассистент перестаёт видеть вложения.

Закрепляем два свойства:
* годный ответ доезжает, и запрос несёт ключ (ручки `/media/*` закрыты);
* любой отказ превращается в заглушку, а не в исключение на пути загрузки.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from service.services.chat.infrastructure.media import openai_media_analysis_adapter as adapter

KEY = "gw-secret-key"


@pytest.fixture()
def _cfg(monkeypatch):
    """Конфиг с адресом сайдкара и ключом.

    ⚠️ Ключ ASCII: заголовки HTTP кодируются latin-1, и настоящий httpx на кириллице
    падает — самодельные дублёры это прятали.
    """
    cfg = SimpleNamespace(
        agents=SimpleNamespace(sidecar_url="http://agents:8090", llm_gateway_api_key=KEY)
    )
    monkeypatch.setattr("service.settings.config", cfg, raising=False)
    return cfg


def _patch(monkeypatch, *, status=200, payload=None, boom=None):
    """Подменяет ТРАНСПОРТ клиента, оставляя сам клиент рабочим.

    Подмена самого `_sidecar_media` проверяла бы заглушку вместо кода: заголовки, разбор
    единой формы ошибки и классификация отказа остались бы непокрытыми.
    """
    seen: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["json"] = json.loads(request.content.decode("utf-8")) if request.content else None
        if boom is not None:
            raise httpx.ConnectError(str(boom))
        return httpx.Response(status, json=payload if payload is not None else {})

    transport = httpx.MockTransport(_handler)
    original = adapter._client

    def _factory(config):
        client = original(config)
        client._transport = transport
        return client

    monkeypatch.setattr(adapter, "_client", _factory)
    return seen


@pytest.mark.asyncio
async def test_image_description_reaches_the_model(monkeypatch, _cfg) -> None:
    seen = _patch(monkeypatch, payload={"text": "на фото кот"})

    text = await adapter.OpenAIMediaAnalysisAdapter().analyze_image(
        b"\x89PNG", "image/png", "a.png"
    )

    assert text == "на фото кот"
    assert seen["url"] == "http://agents:8090/media/describe-image"
    # Ручки `/media/*` закрыты ключом — без заголовка это 401 и молчаливая заглушка.
    assert seen["headers"]["authorization"] == f"Bearer {KEY}"
    assert seen["json"]["content_type"] == "image/png"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "case"),
    [
        ({"boom": "сеть легла"}, "сосед недоступен"),
        ({"status": 503, "payload": {"error": "media_unavailable"}}, "сосед отвечает 5xx"),
        ({"status": 422, "payload": {"error": "invalid_request"}}, "нас отвергли"),
    ],
)
async def test_any_failure_becomes_a_placeholder_not_a_crash(
    monkeypatch, _cfg, kwargs, case
) -> None:
    """Отказ обязан стать заглушкой: загрузка файла из-за него падать не должна.

    ⚠️ Это осознанный fail-open, и теперь он ЯВНЫЙ — раньше был встроен в транспорт, где
    «формат не поддержан» и «сервис лёг» сводились к одному `return None`.
    """
    _patch(monkeypatch, **kwargs)

    text = await adapter.OpenAIMediaAnalysisAdapter().analyze_image(b"x", "image/png", "cat.png")

    assert "cat.png" in text, case
    # 🔴 Заглушка обязана СКАЗАТЬ, что картинку не смотрели, и запретить домысливание.
    # Прежняя «[Изображение загружено: cat.png]» этого не говорила, и модель принимала
    # имя файла за повод описать содержимое.
    assert "НЕ УДАЛОСЬ" in text and "не угадывай" in text, case


@pytest.mark.asyncio
async def test_provider_transcription_falls_back_to_placeholder(monkeypatch, _cfg) -> None:
    """Тот же контракт у STT: не смогли — честная заглушка с именем файла."""
    _patch(monkeypatch, status=503, payload={"error": "media_unavailable"})

    text = await adapter.OpenAIMediaAnalysisAdapter().transcribe_audio(
        b"RIFF", "запись.wav", mode="provider"
    )

    assert text == "[Аудио файл: запись.wav, транскрипция недоступна]"


@pytest.mark.asyncio
async def test_provider_transcription_returns_text(monkeypatch, _cfg) -> None:
    seen = _patch(monkeypatch, payload={"text": "привет, это тест"})

    text = await adapter.OpenAIMediaAnalysisAdapter().transcribe_audio(
        b"RIFF", "запись.wav", mode="provider"
    )

    assert text == "привет, это тест"
    assert seen["url"] == "http://agents:8090/media/transcribe"


def _wav_bytes(seconds: float, rate: int = 16000) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_provider_transcription_leaves_billable_mark(monkeypatch, _cfg) -> None:
    """Денежный контракт: успешный провайдерский STT оставляет метку для тарификации.

    Без неё биллинг-блок аплоада не спишет — ровно так путь и был бесплатным.
    """
    _patch(monkeypatch, payload={"text": "распознанный текст"})
    inst = adapter.OpenAIMediaAnalysisAdapter()

    await inst.transcribe_audio(_wav_bytes(4.0), "voice.wav", mode="provider")

    mark = inst.last_transcription
    assert isinstance(mark, dict)
    assert mark["engine"] == "provider"
    assert mark["duration_sec"] > 0, "длительность нужна биллингу (иначе списание пропускается)"
    assert mark["duration_estimated"] is False, "WAV меряется точно"


@pytest.mark.asyncio
async def test_failed_provider_transcription_leaves_no_mark(monkeypatch, _cfg) -> None:
    """Провал → метки нет → нет списания за неудавшуюся транскрипцию."""
    _patch(monkeypatch, status=503, payload={"error": "media_unavailable"})
    inst = adapter.OpenAIMediaAnalysisAdapter()

    await inst.transcribe_audio(b"RIFF", "voice.wav", mode="provider")

    assert inst.last_transcription is None


@pytest.mark.asyncio
async def test_no_sidecar_url_means_placeholder(monkeypatch) -> None:
    """Адрес не задан — тоже заглушка, а не исключение из транспорта.

    Общая база на незаданном адресе бросает `SidecarUnavailable("not_configured")`, и
    важно, что этот случай пойман здесь же: иначе неполная конфигурация роняла бы
    загрузку файла вместо деградации.
    """
    monkeypatch.setattr(
        "service.settings.config",
        SimpleNamespace(agents=SimpleNamespace(sidecar_url="", llm_gateway_api_key=KEY)),
        raising=False,
    )

    text = await adapter.OpenAIMediaAnalysisAdapter().analyze_image(b"x", "image/png", "a.png")

    assert "a.png" in text and "НЕ УДАЛОСЬ" in text
