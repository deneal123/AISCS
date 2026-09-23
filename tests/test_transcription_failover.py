"""Транскрипция аудио доходит до провайдеров.

⚠️ ЭТА ФУНКЦИЯ БЫЛА СЛОМАНА ЦЕЛИКОМ. `transcribe_via_providers` просит у фасада
`build_provider_order`, а фасад его не реэкспортил — `ImportError` на первой же строке
тела. Ручка `/media` (`presentation/routers/capabilities/media.py:61`) не работала вовсе.

Почему это не падало ни на старте, ни в тестах: импорт ОТЛОЖЕННЫЙ (внутри функции), то
есть ошибка возникает при вызове — у пользователя. А единственный тест, который сюда
заглядывал, мокал весь `service.domain.client` целиком и потому проверял свой мок, а не
фасад.

Дублёры ставятся ТАМ, ГДЕ ЧИТАЮТ, — на фасаде, потому что оттуда их берёт `media`.
Побочно это и есть проверка починки: `monkeypatch.setattr` с `raising=True` падает, если
имени в фасаде нет.
"""

from __future__ import annotations

import pytest

from service.domain import media


class _Client:
    """Клиент провайдера: минимум, который нужен `_transcribe_via_provider`."""

    def __init__(self, text: str):
        outer = self

        class _Transcriptions:
            async def create(self, **_kw):
                return type("R", (), {"text": outer.text})()

        class _Audio:
            transcriptions = _Transcriptions()

        self.text = text
        self.audio = _Audio()


def _provider(text: str, models: list[str]):
    """Провайдер-модуль-дублёр в той же утиной форме, что и настоящие."""

    class _Module:
        OPENAI_CLIENT = _Client(text)

        @staticmethod
        async def list_available_models():
            return models

    return _Module


@pytest.fixture
def _providers(monkeypatch):
    """Дублёры ставятся ТАМ, ГДЕ ЧИТАЮТ.

    ⚠️ `media` берёт `build_provider_order` и `get_provider_module` ИЗ ФАСАДА, а фасад
    связал их значением на импорте — патч `registry.build_provider_order` до потребителя
    не доходит. Ровно тот же класс, что описан в докстринге пакета про `ACTIVE_PROVIDER`,
    только для функций; в проде безвреден (их никто не перепривязывает), а в тесте
    определяет, куда целиться.

    Побочно это и есть проверка починки: `monkeypatch.setattr` с `raising=True` падает,
    если имени в фасаде нет.
    """
    import service.domain.client as client_pkg
    from service.domain.client import registry
    from service.domain.client.resilience import provider_policy

    async def _no_drop(names):
        return list(names)

    monkeypatch.setattr(provider_policy, "drop_hard_off", _no_drop)
    monkeypatch.setattr(client_pkg, "build_provider_order", lambda _active: ["p1", "p2"])
    monkeypatch.setattr(
        client_pkg, "get_provider_module", lambda name: registry.PROVIDER_MODULES.get(name)
    )
    return monkeypatch


@pytest.mark.asyncio
async def test_transcription_reaches_a_provider(_providers):
    """Базовое: путь проходим целиком, текст возвращается.

    До починки падало `ImportError`, а не возвращало пустоту, — то есть ручка отдавала
    500, а не «не смогли распознать».
    """
    from service.domain.client import registry

    _providers.setattr(
        registry, "PROVIDER_MODULES", {"p1": _provider("расшифровка", ["whisper-1"])}
    )

    assert await media.transcribe_via_providers(b"\x00", "a.wav") == "расшифровка"


@pytest.mark.asyncio
async def test_failover_to_the_next_provider(_providers):
    """Первый провайдер без клиента — идём ко второму, а не сдаёмся.

    Ровно ради этого функция и переписывалась с «только активный» на обход очереди.
    """
    from service.domain.client import registry

    class _NoClient:
        OPENAI_CLIENT = None

        @staticmethod
        async def list_available_models():  # pragma: no cover — не должен вызываться
            return []

    _providers.setattr(
        registry,
        "PROVIDER_MODULES",
        {"p1": _NoClient, "p2": _provider("со второго", ["whisper-1"])},
    )

    assert await media.transcribe_via_providers(b"\x00", "a.wav") == "со второго"


@pytest.mark.asyncio
async def test_nobody_could_transcribe_returns_empty(_providers):
    """⚠️ Никто не смог — пустая строка, а не исключение.

    Вызывающий отличает «не распознали» от «сломались»; исключение здесь превратило бы
    первое во второе.
    """
    from service.domain.client import registry

    class _NoClient:
        OPENAI_CLIENT = None

        @staticmethod
        async def list_available_models():  # pragma: no cover
            return []

    _providers.setattr(registry, "PROVIDER_MODULES", {"p1": _NoClient, "p2": _NoClient})

    assert await media.transcribe_via_providers(b"\x00", "a.wav") == ""
