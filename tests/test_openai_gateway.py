"""Тесты маршрутизации OpenAI-совместимого шлюза (provider-префикс модели)."""

from service.presentation.routers.gateway.openai_v1 import _split_model


def test_split_model_known_prefix():
    assert _split_model("openrouter:openai/gpt-4o-mini") == ("openrouter", "openai/gpt-4o-mini")
    assert _split_model("gigachat:GigaChat") == ("gigachat", "GigaChat")
    assert _split_model("mws:mws-gpt-alpha") == ("mws", "mws-gpt-alpha")


def test_split_model_no_prefix():
    assert _split_model("openai/gpt-4o-mini") == (None, "openai/gpt-4o-mini")
    assert _split_model("gpt-4o-mini") == (None, "gpt-4o-mini")
    assert _split_model("") == (None, "")


def test_split_model_unknown_prefix_is_not_a_provider():
    # неизвестный префикс — не провайдер, модель отдаётся как есть
    assert _split_model("foo:bar") == (None, "foo:bar")
