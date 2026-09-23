"""Фабрика провайдеров: то, что раньше было скопировано в каждый клиент.

⚠️ ЗАЧЕМ ЭТОТ ФАЙЛ ПОЯВИЛСЯ ОТДЕЛЬНО. Сразу после переноса четырёх клиентов на фабрику
я прогнал по ней мутации: снимок состояния вместо живого, `None` вместо `AttributeError`,
отключённый `force_chat_completions_api`, `rebuild` без сброса кэша, потерянные
заголовки. ВСЕ ПЯТЬ остались зелёными на полном наборе из 706 тестов — центральный узел
провайдер-слоя не был защищён ничем. Косвенные тесты провайдеров этого не ловят: они
проверяют, что вызов дошёл, а не КАК собран клиент.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from service.domain.client.providers import runtime as pr
from service.domain.client.providers.spec import ProviderSpec

_SPEC = ProviderSpec(
    name="acme",
    label="ACME",
    default_base_url="https://acme.invalid",
    api_key_field="openrouter_api_key",  # реальное поле: спека ссылается по имени
    default_headers=(("X-Title", "GPTHub"),),
)


class _FakeOpenAI:
    """Дублёр AsyncOpenAI: запоминает, с чем его собрали."""

    instances: list[_FakeOpenAI] = []

    def __init__(self, **kw):
        self.kw = kw
        _FakeOpenAI.instances.append(self)


class _ClosableClient:
    def __init__(self) -> None:
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1


@pytest.fixture
def sdk(monkeypatch):
    """Подменяем конструктор клиента и биндеры SDK; отдаём журнал вызовов."""
    _FakeOpenAI.instances.clear()
    log: dict = {"api": []}
    monkeypatch.setattr(pr, "AsyncOpenAI", _FakeOpenAI)
    monkeypatch.setattr(pr, "set_default_openai_api", lambda api: log["api"].append(api))
    monkeypatch.setattr(pr, "set_default_openai_client", lambda _c: None)
    monkeypatch.setattr(pr, "set_default_openai_key", lambda _k: None)
    monkeypatch.setattr(pr, "set_tracing_disabled", lambda *, disabled: None)
    return log


@pytest.fixture
def with_key(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "openrouter_api_key", "sk-первый")
    return monkeypatch


# --------------------------------------------------------------------------- #
# Живое состояние                                                               #
# --------------------------------------------------------------------------- #
def test_state_is_live_after_rebuild(sdk, with_key):
    """⚠️ САМОЕ ВАЖНОЕ СВОЙСТВО: после пересборки читатели видят НОВЫЙ клиент.

    Ради этого состояние и уехало из модуля в рантайм. Раньше каждый клиент держал
    `OPENAI_CLIENT` глобалом и переписывал его через `global`; прочитавший значением
    навсегда оставался со старым — симптом «заменил мёртвый ключ в админке, ничего не
    починилось».
    """
    runtime = pr.ProviderRuntime(_SPEC)
    getattr_ = pr.module_getattr(runtime)
    before = getattr_("OPENAI_CLIENT")

    with_key.setattr("service.settings.config.agents.openrouter_api_key", "sk-второй")
    runtime.rebuild()

    after = getattr_("OPENAI_CLIENT")
    assert before is not after, "прокси отдал снимок — пересборка до читателей не дойдёт"
    assert after.kw["api_key"] == "sk-второй"


def test_unknown_attribute_raises_not_returns_none(sdk, with_key):
    """⚠️ `hasattr` обязан давать False на неизвестное имя.

    `active.get_openai_client` проверяет наличие метода через `hasattr`. Молчаливый
    `None` сделал бы проверку всегда-истинной, и вместо фолбэка вызвался бы `None()`.
    """
    getattr_ = pr.module_getattr(pr.ProviderRuntime(_SPEC))

    with pytest.raises(AttributeError):
        getattr_("нет_такого_имени")


def test_state_names_are_all_served(sdk, with_key):
    getattr_ = pr.module_getattr(pr.ProviderRuntime(_SPEC))

    assert getattr_("OPENAI_API_KEY") == "sk-первый"
    assert getattr_("BASE_URL") == "https://acme.invalid/v1"
    assert getattr_("OPENAI_CLIENT") is not None


# --------------------------------------------------------------------------- #
# Сборка клиента по спеке                                                       #
# --------------------------------------------------------------------------- #
def test_headers_from_spec_reach_the_client(sdk, with_key):
    """Заголовки — не косметика: без атрибуции OpenRouter режет лимиты."""
    pr.ProviderRuntime(_SPEC)

    assert _FakeOpenAI.instances[-1].kw["default_headers"] == {"X-Title": "GPTHub"}


def test_no_headers_means_none_not_empty_dict(sdk, with_key):
    pr.ProviderRuntime(replace(_SPEC, default_headers=()))

    assert _FakeOpenAI.instances[-1].kw["default_headers"] is None


@pytest.mark.parametrize(
    ("force", "expected"),
    [(True, ["chat_completions"]), (False, [])],
    ids=["переключаем", "оставляем Responses API"],
)
def test_responses_api_switch_follows_the_spec(sdk, with_key, force, expected):
    """⚠️ `False` — только у нативного OpenAI, он один умеет Responses API.

    Остальные отвечают на `/responses` 404 (у OpenRouter — HTML), и агенты уходили бы в
    фолбэк на КАЖДОМ запросе.
    """
    pr.ProviderRuntime(replace(_SPEC, force_chat_completions_api=force))

    assert sdk["api"] == expected


def test_empty_base_url_becomes_none(sdk, with_key):
    """Пустая база едет как `None` — тогда SDK берёт свой дефолт (случай OpenAI)."""
    pr.ProviderRuntime(replace(_SPEC, default_base_url="", base_url_suffix=None))

    assert _FakeOpenAI.instances[-1].kw["base_url"] is None


# --------------------------------------------------------------------------- #
# Ключ и база                                                                   #
# --------------------------------------------------------------------------- #
def test_admin_override_wins_over_settings(sdk, with_key):
    """Замена ключа в админке обязана перебивать env — ради неё всё и затевалось."""
    from service.domain.client.providers import credentials

    credentials.set_override("acme", "sk-из-админки")
    try:
        assert pr.ProviderRuntime(_SPEC).api_key == "sk-из-админки"
    finally:
        credentials.clear_override("acme")


def test_fallback_field_is_used_when_primary_is_empty(sdk, monkeypatch):
    """Запасное поле ключа — наследие прежнего именования у MWS."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "openrouter_api_key", "")
    monkeypatch.setattr(config.agents, "openai_api_key", "sk-запасной")

    spec = replace(_SPEC, api_key_fallback_fields=("openai_api_key",))

    assert pr.ProviderRuntime(spec).api_key == "sk-запасной"


def test_missing_key_yields_no_client(sdk, monkeypatch):
    """Нет ключа — нет клиента, и это НЕ исключение: фейловер пойдёт к следующему."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "openrouter_api_key", "")

    assert pr.ProviderRuntime(_SPEC).client is None


def test_required_base_url_blocks_the_client(sdk, with_key, monkeypatch):
    """⚠️ У MWS база ОБЯЗАТЕЛЬНА: без неё клиент бессмыслен, но ключ есть."""
    spec = replace(
        _SPEC, requires_base_url=True, default_base_url="", base_url_field="mws_base_url"
    )
    from service.settings import config

    monkeypatch.setattr(config.agents, "mws_base_url", "")

    assert pr.ProviderRuntime(spec).client is None


def test_key_stripping_follows_the_spec(sdk, monkeypatch):
    """⚠️ У MWS ключ исторически НЕ обрезается — разница сохранена намеренно."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "openrouter_api_key", "  sk-с-пробелами  ")

    stripped = pr.ProviderRuntime(_SPEC).api_key
    kept = pr.ProviderRuntime(replace(_SPEC, strip_api_key=False)).api_key

    assert stripped == "sk-с-пробелами"
    assert kept == "  sk-с-пробелами  "


# --------------------------------------------------------------------------- #
# Хуки: экзотика, которую не выразить декларацией                               #
# --------------------------------------------------------------------------- #
def test_http_client_hook_replaces_the_generic_one(sdk, with_key):
    """⚠️ Потеря этого хука = GigaChat без OAuth и без TLS Минцифры.

    Его HTTP-клиент несёт и auth-слой, ставящий Bearer на каждый запрос, и политику
    проверки сертификатов. Уйди фабрика на общий клиент — запросы полетели бы
    неаутентифицированными, и это не поймал бы ни один тест диалекта.
    """
    marker = object()
    hooks = pr.ProviderHooks(http_client_factory=lambda: marker)

    pr.ProviderRuntime(_SPEC, hooks)

    assert _FakeOpenAI.instances[-1].kw["http_client"] is marker


def test_sdk_key_hook_shields_the_real_key(sdk, with_key):
    """⚠️ В SDK едет ЗАГЛУШКА, а «настроен ли провайдер» считается по настоящему ключу.

    У GigaChat `AsyncOpenAI` требует непустой api_key, но реальный Bearer ставит
    auth-слой. Если бы проверка смотрела на заглушку, провайдер выглядел бы настроенным
    ВСЕГДА — даже без ключа, — и фейловер уходил бы в заведомо мёртвого.
    """
    hooks = pr.ProviderHooks(sdk_api_key=lambda: "заглушка")

    runtime = pr.ProviderRuntime(_SPEC, hooks)

    assert _FakeOpenAI.instances[-1].kw["api_key"] == "заглушка"
    assert runtime.api_key == "sk-первый", "проверка настроенности смотрит на настоящий ключ"
    assert pr.module_getattr(runtime)("OPENAI_API_KEY") == "заглушка"


def test_sdk_key_hook_does_not_fake_being_configured(sdk, monkeypatch):
    """Обратная сторона: заглушка НЕ делает провайдера настроенным при пустом ключе."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "openrouter_api_key", "")
    hooks = pr.ProviderHooks(sdk_api_key=lambda: "заглушка")

    assert pr.ProviderRuntime(_SPEC, hooks).client is None


def test_rebuild_hook_runs_before_rebuilding(sdk, with_key):
    """⚠️ У GigaChat это сброс OAuth-менеджера.

    Без него после замены ключа висел бы СТАРЫЙ Bearer до истечения срока — то есть
    админ меняет ключ, а провайдер продолжает ходить со старым.
    """
    order: list[str] = []
    hooks = pr.ProviderHooks(
        on_rebuild=lambda: order.append("сброс"),
        http_client_factory=lambda: order.append("сборка") or object(),
    )

    runtime = pr.ProviderRuntime(_SPEC, hooks)
    order.clear()
    runtime.rebuild()

    assert order == ["сброс", "сборка"], f"хук не вызван или вызван не до сборки: {order}"


def test_no_hooks_means_generic_path(sdk, with_key):
    """⚠️ У обычного провайдера хуков нет вовсе — и путь у него общий.

    Без этой проверки можно было бы «на всякий случай» завести хуки всем, и экзотика
    перестала бы быть заметной.
    """
    runtime = pr.ProviderRuntime(_SPEC)

    assert runtime.hooks.http_client_factory is None
    assert runtime.hooks.sdk_api_key is None
    assert runtime.hooks.chat_completion is None
    assert runtime.hooks.on_rebuild is None
    assert _FakeOpenAI.instances[-1].kw["api_key"] == "sk-первый"


# --------------------------------------------------------------------------- #
# Кэш моделей                                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rebuild_clears_the_model_cache(sdk, with_key):
    """⚠️ Иначе после смены ключа остаётся список моделей ПРЕЖНЕГО аккаунта."""
    calls = {"n": 0}

    class _Client:
        class models:  # noqa: N801 — форма API OpenAI
            @staticmethod
            async def list():
                calls["n"] += 1
                return type("R", (), {"data": [{"id": "m-1"}]})()

    runtime = pr.ProviderRuntime(_SPEC)
    await runtime.list_available_models(client=_Client())
    await runtime.list_available_models(client=_Client())
    assert calls["n"] == 1, "кэш не сработал — предпосылка теста неверна"

    runtime.rebuild()
    await runtime.list_available_models(client=_Client())

    assert calls["n"] == 2, "rebuild не сбросил кэш моделей"


@pytest.mark.asyncio
async def test_generation_rotation_publishes_client_and_catalog_atomically(
    sdk, with_key, monkeypatch
):
    from service.domain.client.model_catalog import (
        ModelCatalogSource,
        ModelCatalogStatus,
        ProviderModelCatalog,
    )

    runtime = pr.ProviderRuntime(_SPEC)
    running = runtime.acquire_generation()
    entered = asyncio.Event()
    release = asyncio.Event()
    catalog = ProviderModelCatalog(
        provider="acme",
        models=("qualified",),
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )

    async def _catalog(**_kwargs):
        entered.set()
        await release.wait()
        return catalog

    monkeypatch.setattr(runtime.models, "get_snapshot", _catalog)
    with_key.setattr("service.settings.config.agents.openrouter_api_key", "sk-next")
    task = asyncio.create_task(runtime.rebuild_generation())
    await entered.wait()

    during = runtime.acquire_generation()
    assert during.client is running.client
    assert during.catalog is running.catalog

    release.set()
    await task
    future = runtime.acquire_generation()
    assert future.client is not running.client
    assert future.catalog is catalog
    running.release()
    during.release()
    future.release()


@pytest.mark.asyncio
async def test_failed_generation_rebuild_blocks_new_runs_and_drains_candidate(
    sdk, with_key, monkeypatch
):
    runtime = pr.ProviderRuntime(_SPEC)
    running = runtime.acquire_generation()
    candidate = _ClosableClient()

    monkeypatch.setattr(runtime, "create_client", lambda **_kwargs: candidate)

    async def _catalog(**_kwargs):
        raise RuntimeError("private upstream response")

    monkeypatch.setattr(runtime.models, "get_snapshot", _catalog)
    with pytest.raises(RuntimeError, match="private upstream response"):
        await runtime.rebuild_generation()

    next_run = runtime.acquire_generation()
    assert running.client is not None
    assert next_run.client is None
    next_run.release()
    running.release()
    await asyncio.sleep(0)
    assert candidate.close_count == 1


@pytest.mark.asyncio
async def test_cancelled_generation_rebuild_never_publishes_partial_candidate(
    sdk, with_key, monkeypatch
):
    runtime = pr.ProviderRuntime(_SPEC)
    running = runtime.acquire_generation()
    candidate = _ClosableClient()
    entered = asyncio.Event()

    monkeypatch.setattr(runtime, "create_client", lambda **_kwargs: candidate)

    async def _catalog(**_kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime.models, "get_snapshot", _catalog)
    task = asyncio.create_task(runtime.rebuild_generation())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    next_run = runtime.acquire_generation()
    assert running.client is not None
    assert next_run.client is None
    next_run.release()
    running.release()
    await asyncio.sleep(0)
    assert candidate.close_count == 1
