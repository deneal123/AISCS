"""Мёртвая цепочка эмбеддеров объясняет СЕБЯ, а не молчит.

⚠️ ЖИВОЙ ИНЦИДЕНТ. Документ пользователя не попал в базу знаний. В логах было ровно две
строки: «Эмбеддер 'gigachat:Embeddings' упал: 429» и голое «нет доступного эмбеддера».
По такому следу невозможно понять главное — что ЗАПАСНОЙ эмбеддер вообще НЕ ПРОБОВАЛСЯ:
его провайдер (openrouter) числился выключенным, и цикл пропустил его молчаливым
`continue`.

Три разных состояния сходились в одно сообщение, а чинятся они по-разному:
* провайдер основного эмбеддера отдал ошибку (лимиты/ключ) — ждать/сменить ключ;
* фолбэк есть, но его провайдер выключен админом или заблокирован health-проверкой —
  включить провайдера;
* фолбэков нет вовсе — дописать конфиг.

Поэтому проверки ниже смотрят на ЛОГИ и текст исключения: результат («упало») при всех
трёх причинах одинаков, и отличить их можно только по следу.
"""

from __future__ import annotations

import logging

import pytest

from service.domain.tools import vector_store as vs


class _FakeClient:
    def __init__(self, *, fail: bool = False, dimension: int = 2):
        self.embeddings = self
        self.fail = fail
        self.dimension = dimension

    async def create(self, *, model, input):  # noqa: A002 — сигнатура SDK
        if self.fail:
            raise RuntimeError("Error code: 429 - Too Many Requests")

        class _R:
            data = [type("E", (), {"embedding": [0.1] * self.dimension})() for _ in input]

        return _R()


@pytest.fixture
def two_candidates(monkeypatch):
    """Основной + один фолбэк — как в дефолтной конфигурации."""
    monkeypatch.setattr(
        vs,
        "_embedder_candidates",
        lambda: [
            {"model": "gigachat:Embeddings", "dim": 1024},
            {"model": "openrouter:openai/text-embedding-3-small", "dim": 1536},
        ],
    )


@pytest.mark.asyncio
async def test_skipped_fallback_is_explained(monkeypatch, two_candidates, caplog):
    """⚠️ ГЛАВНОЕ: пропуск фолбэка из-за выключенного провайдера обязан быть в логах.

    Именно этот случай и был в проде: основной 429, единственный фолбэк выключен —
    а в логах ни слова о том, что его не пробовали.
    """
    import service.domain.client as client_mod

    async def _unavailable():
        return {"openrouter"}  # фолбэк выключен/заблокирован

    monkeypatch.setattr(client_mod.provider_policy, "unavailable_providers", _unavailable)
    monkeypatch.setattr(client_mod, "get_provider_module", lambda name: object())
    monkeypatch.setattr(client_mod, "get_active_provider", lambda: "gigachat", raising=False)
    monkeypatch.setattr(vs, "_embedder_candidates", vs._embedder_candidates, raising=False)

    # У основного клиент есть и падает 429; фолбэк до клиента не доходит.
    def _module(name):
        mod = type("M", (), {})()
        mod.OPENAI_CLIENT = _FakeClient(fail=True)
        return mod

    monkeypatch.setattr(client_mod, "get_provider_module", _module)

    with caplog.at_level(logging.ERROR), pytest.raises(Exception) as exc:
        await vs._embed_with_dim(["текст"])

    joined = " ".join(r.message for r in caplog.records)
    assert "embedding unavailable code=unavailable" in joined
    assert str(exc.value) == "unavailable"
    assert "429" not in joined


@pytest.mark.asyncio
async def test_working_fallback_is_used_and_marked_non_primary(monkeypatch, two_candidates):
    """Рабочий фолбэк применяется, и он помечен как НЕ основной.

    Это различие критично: пересоздавать общую коллекцию под новый dim можно только при
    смене основного эмбеддера, но не при транзиентном фолбэке — иначе мигание провайдера
    стёрло бы векторы всех пользователей.
    """
    import service.domain.client as client_mod

    async def _unavailable():
        return set()

    monkeypatch.setattr(client_mod.provider_policy, "unavailable_providers", _unavailable)

    def _module(name):
        mod = type("M", (), {})()
        # основной падает, фолбэк работает
        mod.OPENAI_CLIENT = _FakeClient(
            fail=(name == "gigachat"),
            dimension=1024 if name == "gigachat" else 1536,
        )
        return mod

    monkeypatch.setattr(client_mod, "get_provider_module", _module)
    monkeypatch.setattr(client_mod, "get_active_provider", lambda: "gigachat", raising=False)

    vectors, dim, is_primary = await vs._embed_with_dim(["текст"])

    assert vectors, "фолбэк не отработал"
    assert dim == 1536, "взята размерность не фолбэка"
    assert is_primary is False, (
        "фолбэк помечен как основной — пересоздание коллекции стёрло бы чужие векторы"
    )


def test_fallback_chain_has_more_than_one_spare():
    """⚠️ Цепочка из ОДНОГО запасного — это не отказоустойчивость.

    Живой инцидент: основной (gigachat) отдал 429, единственный фолбэк (openrouter) был
    заблокирован health с «Key limit exceeded» — и индексация документов встала целиком,
    файл пользователя не попал в базу знаний. Один запасной означает, что любая пара
    «основной болеет + запасной болеет» кладёт функцию насмерть.
    """
    from service.settings import config

    fallbacks = [c for c in (config.agents.doc_embedder_fallback or []) if c.get("model")]

    assert len(fallbacks) >= 2, (
        f"запасных эмбеддеров {len(fallbacks)} — при болезни основного и единственного "
        "запасного индексация документов умирает целиком"
    )


def test_fallbacks_are_on_different_providers():
    """Запасные обязаны быть у РАЗНЫХ провайдеров.

    Два фолбэка на одном провайдере не спасают: он выключается целиком (ключ, лимит,
    health-блокировка), и оба уходят вместе с ним.
    """
    from service.settings import config

    providers = {
        str(c.get("model", "")).split(":", 1)[0]
        for c in (config.agents.doc_embedder_fallback or [])
        if c.get("model")
    }
    primary_provider = str(config.agents.doc_embedder_model or "").split(":", 1)[0]

    assert len(providers) >= 2, f"все запасные у одного провайдера: {providers}"
    assert primary_provider not in providers or len(providers) > 1, (
        "запасной совпадает с основным провайдером — он умрёт вместе с ним"
    )
