"""Текст, который читает пользователь, пишет ВЫБРАННАЯ им модель."""

from __future__ import annotations

import inspect

from service.domain.subagents import image_generation


def test_fallback_prompt_uses_the_users_model():
    """🔴 Живая жалоба: «выбрал модель, а отвечает другая».

    Промпт-фолбэк — это ТЕКСТ, который человек читает вместо картинки. Он брался
    `pick_text_model(models)`, то есть произвольным дешёвым дефолтом, хотя
    `pick_meta_model(models, preferred)` заведён ровно затем, чтобы уважать выбор.
    """
    src = inspect.getsource(image_generation)

    assert "pick_text_model(models)" not in src, "выбор пользователя снова игнорируется"
    assert src.count("pick_meta_model(models, self.preferred_model())") == 1
    assert src.count("pick_meta_model(chat_models, self.preferred_model())") == 1, (
        "не все текстовые вызовы субагента уважают выбранную модель"
    )
