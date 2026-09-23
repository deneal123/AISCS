"""Неудачная генерация картинки объясняется, а не проходит молча.

🔴 Живой случай: пользователь попросил картинку, получил «Не удалось сгенерировать
изображение» плюс стену промпта и счёт в 37 кредитов. Ни причины, ни следа в логах —
`grep` по всему логу сайдкара не нашёл НИ ОДНОЙ строки о сбое. Разбираться было не с
чем: пустой ответ image-модальности не бросает исключение, а прежний код логировал
только исключения.

При этом обе проверки тем же запросом сразу после ПРОШЛИ — сбой был разовым. Это и есть
задокументированный частый случай (перегрузка, отказ модерации, «извинение» текстом),
и он неотличим от отказа навсегда.
"""

from __future__ import annotations

import logging

import pytest

from service.domain.tools import image_gen


class _Msg:
    def __init__(self, images=None, content="", refusal=None):
        self.images = images
        self.content = content
        self.refusal = refusal


class _Choice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason


class _Resp:
    def __init__(self, message, finish_reason="stop"):
        self.choices = [_Choice(message, finish_reason)]
        self.usage = None


class _Client:
    """Отдаёт заготовленные ответы по очереди и считает попытки."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

        class _Completions:
            @staticmethod
            async def create(**_kw):
                self.calls += 1
                return self._responses.pop(0)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _install(monkeypatch, client):
    async def _catalog():
        return ([], {})

    monkeypatch.setattr(image_gen, "_extract_b64", image_gen._extract_b64)
    monkeypatch.setattr("service.domain.client.get_model_catalog", _catalog, raising=False)
    monkeypatch.setattr("service.domain.client.get_openai_client", lambda: client, raising=False)
    monkeypatch.setattr(
        "service.domain.client.get_provider_module", lambda _name: None, raising=False
    )


_IMAGE = [{"image_url": {"url": "data:image/png;base64,aGVsbG8="}}]


@pytest.mark.asyncio
async def test_empty_response_is_retried_once(monkeypatch):
    """🔴 Разовый пустой ответ не должен становиться отказом для пользователя."""
    client = _Client([_Resp(_Msg(content="…")), _Resp(_Msg(images=_IMAGE))])
    _install(monkeypatch, client)

    b64 = await image_gen.generate_image_b64("m", "нарисуй кота")

    assert b64 == "aGVsbG8=", "повтора не было — пользователь получил бы отказ на ровном месте"
    assert client.calls == 2


@pytest.mark.asyncio
async def test_retry_is_not_endless(monkeypatch):
    """Повтор ОДИН: провайдер берёт деньги и за пустую попытку, платит платформа."""
    client = _Client([_Resp(_Msg(content="нет")), _Resp(_Msg(content="нет"))])
    _install(monkeypatch, client)

    assert await image_gen.generate_image_b64("m", "нарисуй кота") == ""
    assert client.calls == 2


@pytest.mark.asyncio
async def test_success_does_not_retry(monkeypatch):
    client = _Client([_Resp(_Msg(images=_IMAGE))])
    _install(monkeypatch, client)

    await image_gen.generate_image_b64("m", "нарисуй кота")

    assert client.calls == 1, "лишний вызов к платному провайдеру"


@pytest.mark.asyncio
async def test_failure_reason_is_bounded_before_leaving_provider_adapter(monkeypatch):
    client = _Client(
        [
            _Resp(_Msg(content="I can't create images of real people."), "content_filter"),
            _Resp(_Msg(content="I can't create images of real people."), "content_filter"),
        ]
    )
    _install(monkeypatch, client)
    reason: dict = {}

    await image_gen.generate_image_b64("m", "нарисуй Лизу", reason_out=reason)

    assert reason["failure_code"] == "empty_image"
    assert reason["finish_reason"] == "content_filter"
    assert "real people" not in str(reason)


@pytest.mark.asyncio
async def test_failure_is_logged(monkeypatch, caplog):
    """🔴 Молчание и было дефектом: по логам сбой не находился вовсе."""
    client = _Client([_Resp(_Msg(content="перегружен")), _Resp(_Msg(content="перегружен"))])
    _install(monkeypatch, client)

    logger = logging.getLogger(image_gen.__name__)
    logger.addHandler(caplog.handler)
    previous = logger.level
    logger.setLevel(logging.WARNING)
    try:
        with caplog.at_level(logging.WARNING):
            await image_gen.generate_image_b64("m", "нарисуй кота")
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(previous)

    # ⚠️ Считаем УНИКАЛЬНЫЕ сообщения: перехватчик подключён и корнем, и явно, поэтому
    # каждая запись попадает в `records` дважды — по числу строк судить нельзя.
    messages = {
        r.getMessage()
        for r in caplog.records
        if "image generation returned no artifact" in r.getMessage()
    }
    assert any("attempt=1/2" in m for m in messages), "первая попытка не залогирована"
    assert any("attempt=2/2" in m for m in messages), "повтор не залогирован"
    assert all("перегружен" not in m for m in messages), "в лог попал ответ провайдера"


def test_user_message_names_bounded_reason_and_the_price():
    """Пользователю говорим И причину, И что надбавка не взята.

    «Подозрительно дёшево» без объяснения читается как ошибка тарификации, а не как
    «картинки нет — платы нет».
    """
    from service.domain.subagents.image_generation import _failure_line

    line = _failure_line(
        "google/gemini-2.5-flash-image",
        {"failure_code": "empty_image", "finish_reason": "content_filter"},
    )

    assert "фильтром безопасности" in line
    assert "Надбавка за изображение не взята" in line


def test_user_message_survives_an_unexplained_failure():
    from service.domain.subagents.image_generation import _failure_line

    line = _failure_line("m", {})

    assert "Не удалось" in line
    assert "Надбавка за изображение не взята" in line
