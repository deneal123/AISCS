"""Снимок провайдерной политики: то, что чинит fail-open сайдкара.

Зачем эти тесты. Админ выключает провайдера чекбоксом, а health-проверка блокирует
упавшего — оба состояния живут в БД+Redis BACKEND'а. Сайдкар туда не ходит, поэтому до
снимка он молча отвечал «запрещённых нет» и снятый админом провайдер продолжал бы
принимать трафик — без единой ошибки в логах. Именно эта тишина и опасна, поэтому
фиксируем поведение тестами, а не «проверили руками».

Ключевое различие, которое здесь защищается: **снимка нет** (in-process путь) → читаем
свои источники, поведение прежнее; **снимок есть и пуст** → это осознанный ответ
backend'а «никто не выключен», а не «нет данных».
"""

import asyncio

import pytest

from service.domain.client.resilience import provider_policy
from service.shared import provider_policy_context as ppc
from service.shared.provider_policy_context import (
    describe,
    get_blocked,
    get_disabled,
    remember_snapshot,
    use_snapshot,
)


def build_snapshot(*, disabled=None, blocked=None) -> dict[str, list[str]]:
    """Собрать тело снимка ТАК, КАК ЕГО ПРИСЫЛАЕТ backend.

    Производящая функция живёт у backend (`agents_client/provider_policy_snapshot.py`)
    и сайдкару не принадлежит — импортировать её сюда значило бы снова связать сервисы
    ради теста. Здесь повторена форма провода: нормализация (trim + lower) — то, что
    backend делает перед отправкой, и на что сайдкар вправе рассчитывать.
    """

    def _norm(names):
        if not names:
            return []
        return sorted({str(n).strip().lower() for n in names if str(n).strip()})

    return {"disabled": _norm(disabled), "blocked": _norm(blocked)}


def test_no_snapshot_means_read_your_own_source() -> None:
    """Без снимка контекст молчит — in-process путь не должен ничего заметить."""
    assert get_disabled() is None
    assert get_blocked() is None


def test_empty_snapshot_is_an_answer_not_absence() -> None:
    """«Никто не выключен» ≠ «данных нет»: пустой снимок обязан ПЕРЕКРЫТЬ свой источник."""
    with use_snapshot(build_snapshot(disabled=[], blocked=[])):
        assert get_disabled() == frozenset()
        assert get_blocked() == frozenset()
    assert get_disabled() is None  # вышли — контекст восстановлен


def test_snapshot_normalizes_names() -> None:
    """Имена приходят из БД как есть; сравнение в policy — по нижнему регистру."""
    snapshot = build_snapshot(disabled=[" MWS ", "OpenAI"], blocked=["GigaChat"])
    assert snapshot == {"disabled": ["mws", "openai"], "blocked": ["gigachat"]}
    with use_snapshot(snapshot):
        assert get_disabled() == frozenset({"mws", "openai"})


def test_malformed_snapshot_does_not_break_the_run() -> None:
    """Старый backend пришлёт None/мусор — прогон продолжается на прежнем поведении."""
    for payload in (None, "не словарь", 42, []):
        with use_snapshot(payload):
            assert get_disabled() is None


def test_disabled_providers_prefers_snapshot(monkeypatch) -> None:
    """Сайдкарный путь: снимок главнее локальной runtime-настройки."""
    monkeypatch.setattr(provider_policy, "_enabled_map", lambda: {"openai": True})
    assert provider_policy.disabled_providers() == set()  # без снимка — как раньше

    with use_snapshot(build_snapshot(disabled=["mws", "gigachat"])):
        assert provider_policy.disabled_providers() == {"mws", "gigachat"}


def test_blocked_providers_prefers_snapshot(monkeypatch) -> None:
    """Health-блоки приезжают снимком; Redis/БД сайдкара не касаемся вовсе."""

    def _boom():  # Redis у сайдкара нет — если код туда полезет, тест это покажет
        raise AssertionError("при наличии снимка в Redis ходить не нужно")

    monkeypatch.setattr(provider_policy, "_get_redis", _boom)
    monkeypatch.setattr(provider_policy, "_all_provider_names", lambda: ["openai", "mws"])

    with use_snapshot(build_snapshot(blocked=["mws"])):
        assert asyncio.run(provider_policy.blocked_providers()) == {"mws"}
        # Фильтрация по запрошенным именам сохраняется.
        assert asyncio.run(provider_policy.blocked_providers(["openai"])) == set()


def test_hard_off_composes_from_snapshot(monkeypatch) -> None:
    """Весь read-surface домена сводится к двум функциям — значит чинится разом.

    ``hard_off``/``drop_hard_off`` (порядок фейловера) и ``unavailable_providers``
    (векторное хранилище) считают поверх disabled+blocked, поэтому отдельной правки не
    требуют. Если эта композиция когда-нибудь разъедется — упадёт здесь.
    """
    monkeypatch.setattr(provider_policy, "_enabled_map", lambda: {})
    monkeypatch.setattr(provider_policy, "_all_provider_names", lambda: ["openai", "mws", "giga"])

    with use_snapshot(build_snapshot(disabled=["openai"], blocked=["mws"])):
        assert asyncio.run(provider_policy.hard_off()) == {"openai", "mws"}
        order = asyncio.run(provider_policy.drop_hard_off(["openai", "mws", "giga"]))
        assert order == ["giga"]


def test_snapshot_does_not_leak_between_concurrent_runs() -> None:
    """Два параллельных прогона — две разные политики. Протечка = чужие деньги/провайдеры."""

    async def scenario() -> tuple[frozenset, frozenset]:
        async def run_with(names: list[str]) -> frozenset:
            with use_snapshot(build_snapshot(disabled=names)):
                await asyncio.sleep(0)  # даём шанс переключиться на соседнюю задачу
                return get_disabled()

        first, second = await asyncio.gather(run_with(["mws"]), run_with(["openai"]))
        return first, second

    first, second = asyncio.run(scenario())
    assert first == frozenset({"mws"})
    assert second == frozenset({"openai"})


@pytest.mark.parametrize("field", ["disabled", "blocked"])
def test_snapshot_shape_is_json_serializable(field: str) -> None:
    """Снимок едет в теле /run — он обязан быть простым JSON (списки, не множества)."""
    snapshot = build_snapshot(disabled={"mws"}, blocked={"openai"})
    assert isinstance(snapshot[field], list)


class TestRememberedSnapshot:
    """Запомненный снимок — это про `/v1`: его зовут по OpenAI-протоколу, где поля под
    политику нет, поэтому шлюз берёт последнее, что видел процесс из `/run`."""

    def setup_method(self) -> None:
        ppc._LAST_SEEN = None

    teardown_method = setup_method

    def test_unknown_until_first_run(self) -> None:
        assert describe() == {"known": False, "disabled": [], "blocked": []}
        assert get_disabled() is None  # «не знаю» — читатель работает как раньше

    def test_remembered_snapshot_serves_paths_without_their_own(self) -> None:
        remember_snapshot(build_snapshot(disabled=["mws"], blocked=["openai"]))
        assert get_disabled() == frozenset({"mws"})
        assert get_blocked() == frozenset({"openai"})
        assert describe() == {"known": True, "disabled": ["mws"], "blocked": ["openai"]}

    def test_request_snapshot_wins_over_remembered(self) -> None:
        """Свежий снимок запроса главнее памяти процесса — иначе прогон поехал бы
        по устаревшей политике."""
        remember_snapshot(build_snapshot(disabled=["mws"]))
        with use_snapshot(build_snapshot(disabled=["gigachat"])):
            assert get_disabled() == frozenset({"gigachat"})
        assert get_disabled() == frozenset({"mws"})  # вышли — снова память процесса

    def test_garbage_does_not_wipe_known_policy(self) -> None:
        """Кривой payload — фоновое обогащение, а не повод забыть, что знали."""
        remember_snapshot(build_snapshot(disabled=["mws"]))
        for junk in (None, "не словарь", 42):
            remember_snapshot(junk)
        assert get_disabled() == frozenset({"mws"})
