"""Конфиг сайдкара: устойчивость к тому, как его отдаёт compose.

⚠️ ИЗ ЭТОГО ФАЙЛА УДАЛЕНЫ ДВА ТЕСТА, КОТОРЫЕ СКИПАЛИСЬ ВСЕГДА. Они сверяли
`AgentsConfig` и сборку Redis DSN с общим пакетом `gpthub_core` через
`pytest.importorskip("gpthub_core.settings")`. Пакет ликвидирован — значит
`importorskip` пропускал их на КАЖДОМ прогоне, а набор тестов показывал «зелено».
Исходный докстринг это предвидел («умрёт вместе с общим пакетом»), но удалить забыли,
и файл остался выглядеть страховкой, ничего не страхуя.

Риск, который они закрывали, никуда не делся: настройки читаются из ОКРУЖЕНИЯ по
`env_prefix`, и переименованная переменная молча уезжает на дефолт — ни падения, ни
ошибки, просто выключенный инструмент включается, а таймаут становится чужим.
Сверять теперь не с чем (второй копии нет), поэтому эту роль взял на себя
`scripts/check_settings_manifest.py` — гейт «читается кодом, но не объявлено нигде».

Здесь остаётся то, что проверяемо без второй копии.
"""

from __future__ import annotations

import pytest


def test_empty_string_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """compose отдаёт незаданную переменную как "" — это НЕ должно ронять конфиг.

    Раньше не падало лишь потому, что `.env.*` определял все ~60 переменных. Убери
    одну строку — и числовое поле получило бы "" вместо числа.
    """
    from service.settings import AgentsConfig

    monkeypatch.setenv("AGENTS__MWS_TIMEOUT_SEC", "")
    monkeypatch.setenv("AGENTS__PROVIDER_FAILOVER_ENABLED", "")

    cfg = AgentsConfig()

    assert isinstance(cfg.mws_timeout_sec, (int, float))
    assert isinstance(cfg.provider_failover_enabled, bool)
