"""DIP-шов доступа к admin-настройкам агентов на стороне backend.

Настройки читает `service/infrastructure/*` (graphify, память, провайдерная политика,
скачивание репозитория), а живут они в `service/services/admin/application/`. Прямой
импорт был бы инверсией слоёв, поэтому инфраструктура зовёт порт, а admin-модуль
регистрирует себя в нём на импорте.

Проверяется здесь ровно это: зарегистрированный провайдер побеждает дефолт. Поведение
СНИМКА (когда настройки приезжают в теле запроса) — забота сайдкара, и его тесты
переехали туда вместе с кодом: у backend снимочного пути нет и быть не должно, у него
есть БД.
"""

from service.shared import agent_settings_port as rs_mod
from service.shared.agent_settings_port import runtime_settings


class TestRegisteredProvider:
    def test_default_without_provider(self) -> None:
        """До регистрации порт отдаёт default — как overlay без привязанного репозитория.

        Это не заглушка «на всякий случай»: инфраструктура читает настройки на импорте
        модулей, то есть раньше, чем admin-модуль успевает зарегистрироваться. Падение
        здесь означало бы, что порядок импортов становится значимым.
        """
        original = runtime_settings._provider
        try:
            runtime_settings.set_provider(rs_mod._DefaultProvider())
            assert runtime_settings.get_agents("duckdb_enabled", True) is True
        finally:
            runtime_settings.set_provider(original)

    def test_registered_provider_wins_over_default(self) -> None:
        """Зарегистрированный admin-overlay главнее дефолта — иначе тумблеры не работают."""

        class _Overlay:
            def get_agents(self, name, default=None):
                return "from-backend-overlay"

        original = runtime_settings._provider
        try:
            runtime_settings.set_provider(_Overlay())
            assert runtime_settings.get_agents("duckdb_enabled", True) == "from-backend-overlay"
        finally:
            runtime_settings.set_provider(original)
