"""Слепок admin-настроек агентов: чтобы тумблеры из админки работали и в сайдкаре.

Зачем. Домен читает runtime-настройки через `service.shared.agent_settings` (тумблеры
инструментов, число ретраев, лимиты контекста, порядок фейловера). Overlay живёт в БД
backend'а, куда сайдкар не ходит, — значит в http-режиме он отдавал бы ДЕФОЛТЫ, и
выключенный админом инструмент снова бы включился. Молча, без ошибки: ровно тот же класс
тихой деградации, что и с провайдерной политикой [[test_provider_policy_snapshot]].

Инвариант тот же: слепка НЕТ → ведём себя как раньше (дефолт); ключа нет в слепке →
тоже дефолт (слепок несёт только ПЕРЕОПРЕДЕЛЁННОЕ, а не весь конфиг).
"""

import asyncio

from service.shared import agent_settings as rs_mod
from service.shared.agent_settings import (
    describe_settings,
    remember_settings,
    runtime_settings,
    use_settings,
)


class TestSnapshotProvider:
    """Проверяем СНИМОЧНЫЙ провайдер — то есть поведение САЙДКАРА.

    Ставим его явно: в полном суите какой-нибудь тест импортирует admin-модуль backend'а,
    а тот на импорте регистрирует себя провайдером (и правильно делает — см.
    ``test_registered_provider_still_wins``). Без явной установки эти тесты проверяли бы
    admin-overlay, а не снимок, и зелёными были бы по случайности.
    """

    def setup_method(self) -> None:
        rs_mod._LAST_SEEN = None
        self._saved = runtime_settings._provider
        runtime_settings.set_provider(rs_mod._SnapshotProvider())

    def teardown_method(self) -> None:
        rs_mod._LAST_SEEN = None
        runtime_settings.set_provider(self._saved)

    def test_without_snapshot_returns_default(self) -> None:
        """Backend in-process и юнит-тесты не подают слепок — поведение прежнее."""
        assert runtime_settings.get_agents("duckdb_enabled", True) is True
        assert runtime_settings.get_agents("llm_retry_attempts", 3) == 3

    def test_snapshot_overrides_default(self) -> None:
        """Админ выключил инструмент — сайдкар обязан это увидеть."""
        with use_settings({"duckdb_enabled": False, "llm_retry_attempts": 7}):
            assert runtime_settings.get_agents("duckdb_enabled", True) is False
            assert runtime_settings.get_agents("llm_retry_attempts", 3) == 7
        assert runtime_settings.get_agents("duckdb_enabled", True) is True  # вышли

    def test_key_absent_from_snapshot_falls_back_to_default(self) -> None:
        """Слепок несёт только переопределённое; остальное — из конфига стороны."""
        with use_settings({"duckdb_enabled": False}):
            assert runtime_settings.get_agents("graphify_enabled", True) is True

    def test_falsy_override_is_not_confused_with_absence(self) -> None:
        """False/0/"" — валидные значения, а не «нет ключа». Иначе выключенный тумблер
        читался бы как включённый."""
        with use_settings({"duckdb_enabled": False, "ldr_iterations": 0, "ldr_model": ""}):
            assert runtime_settings.get_agents("duckdb_enabled", True) is False
            assert runtime_settings.get_agents("ldr_iterations", 5) == 0
            assert runtime_settings.get_agents("ldr_model", "gpt-4o") == ""

    def test_remembered_snapshot_serves_paths_without_their_own(self) -> None:
        """`/v1` зовут по OpenAI-протоколу — своего слепка у него быть не может."""
        assert describe_settings()["known"] is False
        remember_settings({"duckdb_enabled": False})
        assert runtime_settings.get_agents("duckdb_enabled", True) is False
        assert describe_settings()["keys"] == ["duckdb_enabled"]

    def test_health_names_the_active_provider(self) -> None:
        """Затащи в сайдкар admin-модуль — он вытеснит снимок молча. Пусть будет видно."""
        assert describe_settings()["provider"] == "_SnapshotProvider"

    def test_request_snapshot_wins_over_remembered(self) -> None:
        remember_settings({"llm_retry_attempts": 1})
        with use_settings({"llm_retry_attempts": 9}):
            assert runtime_settings.get_agents("llm_retry_attempts", 3) == 9
        assert runtime_settings.get_agents("llm_retry_attempts", 3) == 1

    def test_garbage_snapshot_does_not_break_the_run(self) -> None:
        for junk in (None, "не словарь", 42, []):
            with use_settings(junk):
                assert runtime_settings.get_agents("duckdb_enabled", True) is True

    def test_snapshot_does_not_leak_between_concurrent_runs(self) -> None:
        """Два прогона — две разные настройки. Протечка = чужое поведение движка."""

        async def scenario():
            async def run_with(value: int) -> int:
                with use_settings({"llm_retry_attempts": value}):
                    await asyncio.sleep(0)
                    return runtime_settings.get_agents("llm_retry_attempts", 3)

            return await asyncio.gather(run_with(1), run_with(9))

        assert asyncio.run(scenario()) == [1, 9]
