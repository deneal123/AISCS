"""Провайдер ответил без картинки → пользователь НЕ платит за изображение.

🔴 ЖИВАЯ ЖАЛОБА. «изобрази Елизавету Смирнову»: картинка не сгенерировалась (провайдер
image-модальности под нагрузкой вернул ответ без изображения), пользователь получил
текстовый промпт-фолбэк — и списание 4201 кредит, львиная доля которого пришлась на
image-модель, которой он так и не увидел.

Причина — порядок в `generate_image_b64`: `accumulate_usage` стоял БЕЗУСЛОВНО, до
проверки, есть ли в ответе картинка. Провайдер image-модальности иногда отвечает без
изображения, но с непустым usage (и списывает с нас); эти image-токены попадали в счёт
вызывающего, тот видел пустой b64 и уходил в промпт-фолбэк — а пользователь платил по
дорогому image-тарифу за то, чего не получил, плюс за фолбэк.

Тот же принцип, что уже применён в web_search и на таймауте синтеза: с пользователя
берём только за то, что он получил. Неуспешный вызов к провайдеру — наш убыток на
ретрае, а не счёт клиенту.
"""

from __future__ import annotations

import pytest

from service.domain.run_context import PrivateRunResources, use_run_execution
from service.domain.tools import image_gen


class _Resp:
    def __init__(self, content, images):
        msg = type("M", (), {"content": content, "images": images})()
        self.choices = [type("C", (), {"message": msg})()]
        self.usage = type(
            "U", (), {"prompt_tokens": 8, "completion_tokens": 1290, "total_tokens": 1298}
        )()


class _Client:
    def __init__(self, resp):
        self._resp = resp
        self.chat = type("Chat", (), {"completions": self})()

    async def create(self, **kwargs):
        return self._resp


@pytest.fixture
def _patch_catalog(monkeypatch):
    # ⚠️ Патчим в service.domain.client, а НЕ в image_gen: функции импортируются
    # `from service.domain.client import ...` ВНУТРИ generate_image_b64, поэтому имя
    # резолвится в исходном модуле. Иначе в dev-окружении, где провайдеры настроены,
    # каталог отдаёт реального владельца и вызов уходит на живой провайдер мимо фейка.
    import service.domain.client as client_mod

    async def _catalog():
        return ([], {})

    monkeypatch.setattr(client_mod, "get_model_catalog", _catalog, raising=False)
    monkeypatch.setattr(client_mod, "get_provider_module", lambda name: None, raising=False)

    def _set_client(client):
        monkeypatch.setattr(client_mod, "get_openai_client", lambda: client, raising=False)

    return _set_client


@pytest.mark.asyncio
async def test_no_image_no_usage(monkeypatch, _patch_catalog):
    """⚠️ ГЛАВНОЕ. Ответ без картинки → usage НЕ начисляется, b64 пуст."""
    resp = _Resp("извините, не могу", images=None)  # провайдер ответил текстом, без картинки
    _patch_catalog(_Client(resp))

    usage: dict = {}
    with use_run_execution(PrivateRunResources()) as execution:
        b64 = await image_gen.generate_image_b64(
            "google/gemini-2.5-flash-image", "portrait", execution
        )
        receipts = execution.usage.receipts

    assert b64 == "", "картинки в ответе не было, а b64 непустой"
    assert usage == {}, (
        f"начислен image-usage за неполученную картинку — пользователь заплатит за неё: {usage}"
    )
    assert len(receipts) == 2, "обе фактические provider-попытки должны остаться в ledger"
    assert all(not receipt.billable for receipt in receipts)


@pytest.mark.asyncio
async def test_real_image_is_billed(monkeypatch, _patch_catalog):
    """Обратная сторона: картинка ЕСТЬ → usage начисляется (иначе генерация бесплатна)."""
    data_url = "data:image/png;base64,aGVsbG8="
    resp = _Resp(None, images=[{"image_url": {"url": data_url}}])
    _patch_catalog(_Client(resp))

    usage: dict = {}
    with use_run_execution(PrivateRunResources()) as execution:
        b64 = await image_gen.generate_image_b64(
            "google/gemini-2.5-flash-image", "portrait", execution
        )
        receipts = execution.usage.receipts
        usage = execution.usage.as_token_usage()

    assert b64 == "aGVsbG8=", "картинка не извлеклась из корректного ответа"
    assert usage.get("completion") == 1290, (
        f"успешная генерация не затарифицирована — картинки станут бесплатными: {usage}"
    )
    assert len(receipts) == 1
    assert receipts[0].billable is True
