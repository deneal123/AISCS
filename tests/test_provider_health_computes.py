"""`compute_provider_health` реально ВЫПОЛНЯЕТСЯ — со всеми своими импортами.

⚠️ НАЙДЕНО ЖИВЫМ ЗАПУСКОМ. В админ-панели не появлялось состояние провайдеров. Причина:
`/providers/health` отдавал 500, потому что `compute_provider_health` делал
`from . import openrouter_client` — имя, которого фасад больше не отдаёт (провайдер-модули
переехали в `providers/` при переходе на фабрику). `ImportError` ронял всю ручку.

## Почему тест `test_app.py` молчал

Он подменяет `compute_provider_health` ЦЕЛИКОМ (`monkeypatch.setattr(..., _fake_health)`),
то есть проверяет транспорт ручки — код ответа, форму, флаг `force` — но НИ РАЗУ не
выполняет саму функцию. А баг был именно в её первой строке: в отложенном импорте,
который срабатывает только при реальном вызове.

Отсюда этот файл: он зовёт настоящую `compute_provider_health` и лишь глушит СЕТЬ
(пробы провайдеров), не трогая тело функции. Импорты, резолв модулей, сборка структуры —
всё исполняется по-настоящему.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_provider_error_detail_never_echoes_credentials():
    from service.domain.client.health import provider_error_detail

    class _ProviderError(RuntimeError):
        status_code = 401

    detail = provider_error_detail(
        _ProviderError("Authorization: Bearer sk-sensitive-token; key hash=secret-hash")
    )

    assert detail == "auth"
    assert "_ProviderError" not in detail
    assert "sk-" not in detail
    assert "hash" not in detail


@pytest.mark.asyncio
async def test_compute_provider_health_runs_without_import_errors():
    """⚠️ ГЛАВНОЕ: функция доходит до конца, не спотыкаясь об импорт.

    Ключей провайдеров в тестовом окружении нет, поэтому статусы будут «не настроен» —
    но САМА СБОРКА обязана пройти. Ровно она и падала 500-й у пользователя.
    """
    from service.domain.client.health import compute_provider_health

    data = await compute_provider_health(force_probe=False)

    assert isinstance(data, dict), "ручка вернула не словарь"
    providers = data.get("providers")
    assert isinstance(providers, dict), (
        "нет ключа 'providers' — админ-панель ждёт именно его и покажет пустую таблицу"
    )
    assert providers, "ни одного провайдера в сводке — панель будет пустой"


@pytest.mark.asyncio
async def test_health_uses_the_real_openrouter_balance(monkeypatch):
    """⚠️ Баланс OpenRouter резолвится через `providers.openrouter`, а не мёртвое имя.

    Это второе место, где стояло `openrouter_client` — не только в импорте наверху.
    Проверяем, что баланс ДЕЙСТВИТЕЛЬНО зовётся из живого модуля: подменяем
    `fetch_balance` там, где он теперь живёт, и убеждаемся, что health его дёрнул.
    """
    import service.domain.client.providers.openrouter as openrouter_mod

    called = {"balance": False}

    async def _fake_balance():
        called["balance"] = True
        return {"balance": 42.0, "currency": "USD"}

    monkeypatch.setattr(openrouter_mod, "fetch_balance", _fake_balance)
    # Чтобы health дошёл до баланса, openrouter должен считаться настроенным.
    monkeypatch.setattr(
        "service.domain.client.registry.is_configured",
        lambda name: name == "openrouter",
    )

    from service.domain.client.health import compute_provider_health

    data = await compute_provider_health(force_probe=False)

    assert called["balance"], (
        "баланс OpenRouter не запрошен из providers.openrouter — health ссылался бы на "
        "мёртвое имя, и вся ручка снова упала бы 500"
    )
    orouter = (data.get("providers") or {}).get("openrouter") or {}
    # health кладёт баланс тем же объектом, что вернул fetch_balance.
    assert orouter.get("balance") == {"balance": 42.0, "currency": "USD"}, (
        f"баланс не доехал в сводку: {orouter}"
    )


@pytest.mark.asyncio
async def test_only_limits_the_probe_to_named_providers(monkeypatch):
    """⚠️ `only` пробит ТОЛЬКО названных — иначе самопроверка станет пуллингом.

    Проба — настоящий вызов `chat.completions.create` к провайдеру. Периодическая
    задача backend'а спрашивает про заблокированных каждые пять минут; если фильтр
    перестанет действовать, она начнёт бить по ВСЕМ провайдерам, а полный обход
    убирали намеренно (здоровье всех — по кнопке в админке).
    """
    from service.domain.client.health import compute_provider_health

    data = await compute_provider_health(force_probe=False, only=["gigachat"])

    assert set(data.get("providers") or {}) == {"gigachat"}, (
        f"пробили не только названного: {sorted(data.get('providers') or {})}"
    )


@pytest.mark.asyncio
async def test_gigachat_tls_configuration_error_is_bounded(monkeypatch):
    import service.domain.client.registry as registry
    from service.domain.client.health import compute_provider_health

    marker = "S23_PRIVATE_CERTIFICATE_PATH"
    module = SimpleNamespace(
        OPENAI_CLIENT=None,
        configuration_error=lambda: "tls_config",
    )
    monkeypatch.setattr(registry, "is_configured", lambda name: name == "gigachat")
    monkeypatch.setattr(registry, "get_provider_module", lambda _name: module)

    data = await compute_provider_health(force_probe=True, only=["gigachat"])

    info = data["providers"]["gigachat"]
    assert info["error"] == "tls_config"
    assert info["reason"] == "ошибка конфигурации TLS"
    assert marker not in repr(info)


@pytest.mark.asyncio
async def test_empty_only_means_nobody_not_everybody():
    """Пустой список — это «никого». Трактовка «всех» вернула бы полный обход молча."""
    from service.domain.client.health import compute_provider_health

    data = await compute_provider_health(force_probe=True, only=[])

    assert (data.get("providers") or {}) == {}, (
        "пустой фильтр пробил всех — опечатка в вызове тихо возвращает пуллинг"
    )


@pytest.mark.asyncio
async def test_health_exposes_only_bounded_catalog_and_qualification_aggregates(monkeypatch):
    import service.domain.client.registry as registry
    from service.domain.client.health import compute_provider_health
    from service.domain.client.model_catalog import (
        ModelCatalogSource,
        ModelCatalogStatus,
        ProviderModelCatalog,
    )
    from service.domain.client.model_requirements import (
        ModelQualification,
        ProviderQualificationStatus,
    )

    marker = "S31_PRIVATE_PROVIDER_PAYLOAD"
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace()))
    module = SimpleNamespace(OPENAI_CLIENT=client, configuration_error=lambda: None)
    catalog = ProviderModelCatalog(
        provider="gigachat",
        models=("Embeddings-2",),
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )

    async def get_catalog(_name: str, *, force_refresh: bool = False):
        del force_refresh
        return catalog

    async def qualify(name: str, *, requirement, catalog, **_kwargs):
        return ModelQualification(
            provider=name,
            requirement=requirement,
            status=ProviderQualificationStatus.NO_COMPATIBLE_MODEL,
            catalog_source=catalog.source,
            catalog_status=catalog.status,
            candidate_count=0,
        )

    monkeypatch.setattr(registry, "is_configured", lambda name: name == "gigachat")
    monkeypatch.setattr(registry, "get_provider_module", lambda _name: module)
    monkeypatch.setattr(registry, "get_provider_model_catalog", get_catalog)
    monkeypatch.setattr(registry, "qualify_model", qualify)

    data = await compute_provider_health(force_probe=True, only=["gigachat"])

    info = data["providers"]["gigachat"]
    assert info["catalog"] == {
        "source": "live",
        "status": "available",
        "fresh": True,
        "model_count": 1,
    }
    assert info["qualification"] == {
        "chat": "no_compatible_model",
        "tools": "no_compatible_model",
        "vision": "no_compatible_model",
        "image_output": "no_compatible_model",
        "embeddings": "no_compatible_model",
        "transcription": "no_compatible_model",
    }
    assert info["generation"] == {
        "status": "unavailable",
        "retired_count": 0,
        "leased_count": 0,
    }
    assert "models" not in info
    assert marker not in repr(info)
