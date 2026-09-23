"""Тарификация ПРОВАЙДЕРСКОГО STT (денежная дыра из Фазы 1 плана).

Провайдерская транскрипция была бесплатной: сайдкар выбрасывал `resp.usage`, эндпоинт
`/media/transcribe` отдавал только текст, а гейт списания стоял на `engine=="local"`.
У фронта есть тумблер режима — юзер мог выбрать провайдера и транскрибировать даром.

Решение (утверждено): тарифицировать ОБА движка по единой поминутной ставке whisper.
Длительность считается из байтов на backend (WAV точно, сжатые — оценкой), чтобы не-WAV
не давал бесплатной транскрипции.

Ассерт денежных тестов один: сделан платный STT-вызов ⇒ есть списание с kind=transcription.
Мутация (вернуть гейт на `== "local"`) обязана покраснить провайдерский кейс.
"""

from __future__ import annotations

import io
import wave

import pytest

from service.services.chat.infrastructure.media.whisper_local_transcriber import (
    audio_duration_sec,
)
from service.services.chat.presentation.http import upload_api as ua


def _wav_bytes(seconds: float, rate: int = 16000) -> bytes:
    """Валидный WAV mono/16-bit на `seconds` секунд (как voice.wav с фронта)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


class _FakeBilling:
    """Записывает списания вместо реального движка биллинга."""

    def __init__(self) -> None:
        self.charges: list[dict] = []

    async def charge(self, user_id, *, credits, tokens, raw_cost_rub, metadata):
        self.charges.append(
            {"user_id": user_id, "credits": credits, "rub": raw_cost_rub, "metadata": metadata}
        )


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)


# ── audio_duration_sec ────────────────────────────────────────────────────────


def test_wav_duration_is_exact_and_not_estimated():
    dur, estimated = audio_duration_sec(_wav_bytes(3.0))
    assert estimated is False
    assert abs(dur - 3.0) < 0.05, "WAV читается точно stdlib wave"


def test_non_wav_duration_is_estimated_and_nonzero():
    # Сжатый формат без аудио-библиотеки: длительность НЕ обнуляется (иначе бесплатный STT),
    # но помечается оценкой.
    dur, estimated = audio_duration_sec(b"ID3\x03\x00" + b"\x00" * 32000)
    assert estimated is True
    assert dur > 0, "не-WAV не должен давать нулевую (бесплатную) длительность"


def test_empty_audio_is_zero():
    assert audio_duration_sec(b"") == (0.0, False)


# ── денежный гейт _charge_transcription ────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_transcription_is_billed():
    """СУТЬ ФИКСА: провайдерская транскрипция тарифицируется (раньше была даром)."""
    billing = _FakeBilling()
    dur, _ = audio_duration_sec(_wav_bytes(5.0))
    await ua._charge_transcription(
        billing,
        None,
        "user-1",
        "hashA",
        {"engine": "provider", "model": "gpt-audio", "duration_sec": dur},
    )
    assert len(billing.charges) == 1, "провайдерский STT обязан списываться"
    meta = billing.charges[0]["metadata"]
    assert meta["kind"] == "transcription"
    assert meta["engine"] == "provider"
    assert billing.charges[0]["credits"] > 0


@pytest.mark.asyncio
async def test_local_transcription_still_billed():
    billing = _FakeBilling()
    await ua._charge_transcription(
        billing, None, "user-1", "hashL", {"engine": "local", "model": "base", "duration_sec": 5.0}
    )
    assert len(billing.charges) == 1
    assert billing.charges[0]["metadata"]["engine"] == "local"


@pytest.mark.asyncio
async def test_non_transcription_is_not_billed():
    """Гейт не должен списывать за НЕ-транскрипцию (нет метки/чужой движок)."""
    billing = _FakeBilling()
    for payload in (None, {}, {"engine": "image"}, {"engine": "provider", "duration_sec": 0.0}):
        await ua._charge_transcription(billing, None, "u", "h", payload)
    assert billing.charges == [], "без валидной STT-метки списаний быть не должно"


@pytest.mark.asyncio
async def test_provider_charge_is_deduped_on_double_submit():
    billing = _FakeBilling()
    r = _FakeRedis()
    payload = {"engine": "provider", "model": "gpt-audio", "duration_sec": 5.0}
    await ua._charge_transcription(billing, r, "user-1", "hashA", payload)
    await ua._charge_transcription(billing, r, "user-1", "hashA", payload)
    assert len(billing.charges) == 1, "дабл-сабмит той же загрузки списывается один раз"
