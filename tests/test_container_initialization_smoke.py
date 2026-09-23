"""Сборка контейнера зависимостей: все обязательные узлы на месте.

⚠️ ЭТИ ДВА ТЕСТА ПАДАЛИ ВСЕГДА — и локально, и в CI, причём по РАЗНЫМ причинам. Они
строили контейнер из голого `Config()`, то есть из БОЕВОЙ конфигурации по умолчанию:

* локально спотыкались о гард `PAYMENTS__WEBHOOK_SECRET` (mock-провайдер без секрета
  принимает вебхуки без подписи — падение на старте здесь правильное и намеренное);
* в CI — о `PermissionError: /var/lib/app`, боевой каталог хранилища, которого на
  раннере нет и быть не должно.

Из-за них шаг «Pytest (full suite)» был КРАСНЫМ на каждом пуше, то есть блокирующий
гейт backend'а не блокировал ничего: любое НАСТОЯЩЕЕ падение утонуло бы в этих двух.
Предмет тестов — полнота проводки, а не пригодность боевого окружения на машине
разработчика, поэтому минимальное окружение подаётся здесь явно.
"""

import pytest


@pytest.fixture()
def prod_like_env(monkeypatch, tmp_path):
    """Минимум, без которого боевая конфигурация не поднимается НИГДЕ.

    Обе переменные — не «чтобы тест позеленел», а именно то, что в бою приходит из
    `docker/.env.*`: секрет вебхука и каталог хранилища. Значения игрушечные, но
    непустые — проверяется проводка, а не платежи и не файловый ввод-вывод.
    """
    monkeypatch.setenv("PAYMENTS__WEBHOOK_SECRET", "smoke-secret")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))


def test_build_container_smoke_required_dependencies(prod_like_env) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")

    from service.composition.container import build_container
    from service.composition.models import AppContainer
    from service.settings import Config

    app_container = build_container(Config())

    assert isinstance(app_container, AppContainer)
    assert app_container.infra.background_task_manager is not None
    assert app_container.infra.pg_connector is not None
    assert app_container.infra.stream_port is not None
    assert app_container.infra.message_bus_port is not None
    assert app_container.infra.job_queue_port is not None
    assert app_container.repositories.auth_repository is not None
    assert app_container.repositories.job_repository is not None
    assert app_container.repositories.profile_repository is not None
    assert app_container.repositories.file_repository is not None
    assert app_container.services.auth_service is not None
    assert app_container.services.job_service is not None
    assert app_container.services.profile_service is not None
    assert app_container.services.file_saver_service is not None
    assert app_container.services.process_chat_message_handler is not None
    assert app_container.services.new_job_processor is not None


def test_create_app_accepts_container_override(prod_like_env) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")

    from service.composition.container import build_container
    from service.main import create_app
    from service.settings import Config

    app_container = build_container(Config())
    app = create_app(container_override=app_container)

    assert app.state.container is app_container


def test_missing_webhook_secret_still_refuses_to_start(monkeypatch, tmp_path) -> None:
    """⚠️ Гард, о который тесты спотыкались, обязан ОСТАТЬСЯ.

    Иначе «починка» свелась бы к его обходу. Mock-провайдер без секрета не проверяет
    подпись вебхука вовсе: любой неаутентифицированный POST на `/api/billing/webhook`
    начислит кредиты на произвольный `user_id`. Падение на старте — единственное, что
    не даёт пронести такую конфигурацию в бой незамеченной.
    """
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("PAYMENTS__PROVIDER", "mock")
    monkeypatch.setenv("PAYMENTS__WEBHOOK_SECRET", "")

    from service.composition.container import build_container
    from service.settings import Config

    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        build_container(Config())
