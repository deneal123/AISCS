"""Единый источник правды о чат-пригодности модели.

Раньше base._is_blocked_chat_model блокировал только эмбеддеры (свой усечённый
список), а registry.is_chat_capable — полный (эмбеддеры/аудио/картинки/модерация).
Из-за расхождения аудио/картиночная модель могла проскочить как чат-модель. Теперь
base делегирует registry.is_chat_capable.
"""

from service.domain.base import SimpleStreamingAgent


def test_base_blocks_non_chat_models() -> None:
    assert SimpleStreamingAgent._is_blocked_chat_model("whisper-1") is True
    assert SimpleStreamingAgent._is_blocked_chat_model("dall-e-3") is True
    assert SimpleStreamingAgent._is_blocked_chat_model("text-embedding-3-small") is True
    assert SimpleStreamingAgent._is_blocked_chat_model("flux-pro") is True
    assert SimpleStreamingAgent._is_blocked_chat_model("omni-moderation-latest") is True


def test_base_allows_chat_models() -> None:
    assert SimpleStreamingAgent._is_blocked_chat_model("gpt-4o-mini") is False
    assert SimpleStreamingAgent._is_blocked_chat_model("mws-gpt-alpha") is False
    assert SimpleStreamingAgent._is_blocked_chat_model("") is False  # пусто = не блокируем
    assert SimpleStreamingAgent._is_blocked_chat_model(None) is False


def test_base_matches_registry_is_chat_capable() -> None:
    from service.domain.client.registry import is_chat_capable

    for m in ("gpt-4o", "whisper-1", "dall-e-3", "bge-m3", "mws-gpt-alpha", "flux"):
        blocked = SimpleStreamingAgent._is_blocked_chat_model(m)
        assert blocked == (not is_chat_capable(m))


def test_base_picks_chat_over_blocked() -> None:
    picked = SimpleStreamingAgent._pick_chat_capable_model(
        ["whisper-1", "dall-e-3", "mws-gpt-alpha"]
    )
    assert picked == "mws-gpt-alpha"  # аудио/картинки отфильтрованы, выбрана текстовая


def test_base_pick_prefers_text_family() -> None:
    picked = SimpleStreamingAgent._pick_chat_capable_model(["zzz-unknown-model", "gpt-4o"])
    assert picked == "gpt-4o"  # text_re предпочитает известное семейство
