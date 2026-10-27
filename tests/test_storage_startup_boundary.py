"""Explicit object storage must not silently turn into another persistence backend."""

import traceback
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service.composition import infra
from service.composition.storage import StorageConfigurationError, build_file_storage


def test_configured_minio_initialization_failure_does_not_select_local(monkeypatch):
    from service.infrastructure.storage import local_file_storage, minio_file_storage

    sentinel = "PRIVATE_CREDENTIAL https://private.invalid/upload"
    minio = Mock(side_effect=RuntimeError(sentinel))
    local = Mock()
    monkeypatch.setattr(minio_file_storage, "MinioFileStorage", minio)
    monkeypatch.setattr(local_file_storage, "LocalFileStorage", local)
    monkeypatch.setattr(infra, "PgConnector", Mock())
    monkeypatch.setattr(infra, "BackgroundTaskManager", Mock())
    warning = Mock()
    monkeypatch.setattr(infra.logger, "warning", warning)
    config = SimpleNamespace(
        storage=SimpleNamespace(backend="minio"),
        minio=object(),
        pg=object(),
        redis=SimpleNamespace(enabled=False),
    )
    with pytest.raises(RuntimeError) as caught:
        infra.build_infra(config)
    local.assert_not_called()
    assert "PRIVATE" not in str(caught.value)
    assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
    assert "PRIVATE" not in str(warning.call_args_list)


@pytest.mark.parametrize("backend", ["minio", " MINIO "])
def test_explicit_minio_uses_exact_configured_client(monkeypatch, backend):
    from service.infrastructure.storage import local_file_storage, minio_file_storage

    minio_config = object()
    expected = object()
    constructor = Mock(return_value=expected)
    local = Mock()
    monkeypatch.setattr(minio_file_storage, "MinioFileStorage", constructor)
    monkeypatch.setattr(local_file_storage, "LocalFileStorage", local)
    result = build_file_storage(
        SimpleNamespace(storage=SimpleNamespace(backend=backend), minio=minio_config)
    )
    assert result is expected
    constructor.assert_called_once_with(minio_config)
    local.assert_not_called()


@pytest.mark.parametrize("backend", ["local", " LOCAL ", ""])
def test_intentional_local_and_legacy_default_remain_available(monkeypatch, backend):
    from service.infrastructure.storage import local_file_storage

    expected = object()
    constructor = Mock(return_value=expected)
    monkeypatch.setattr(local_file_storage, "LocalFileStorage", constructor)
    assert build_file_storage(SimpleNamespace(storage=SimpleNamespace(backend=backend))) is expected
    constructor.assert_called_once_with()


@pytest.mark.parametrize("backend", ["minoi", "PRIVATE_CREDENTIAL", "https://private.invalid"])
def test_unknown_backend_is_not_an_instruction_to_write_to_local(monkeypatch, backend):
    from service.infrastructure.storage import local_file_storage

    local = Mock()
    monkeypatch.setattr(local_file_storage, "LocalFileStorage", local)
    with pytest.raises(StorageConfigurationError) as caught:
        build_file_storage(SimpleNamespace(storage=SimpleNamespace(backend=backend)))
    assert caught.value.code == "storage_config_invalid"
    assert str(caught.value) == "storage_config_invalid"
    local.assert_not_called()


def test_redis_initialization_failure_has_only_bounded_diagnostics(monkeypatch):
    from service.infrastructure.cache import manager as redis_manager

    monkeypatch.setattr(infra, "build_file_storage", Mock(return_value=object()))
    monkeypatch.setattr(infra, "PgConnector", Mock())
    monkeypatch.setattr(infra, "BackgroundTaskManager", Mock())
    monkeypatch.setattr(infra, "BasicFileScanner", Mock())
    monkeypatch.setattr(
        redis_manager, "RedisManager", Mock(side_effect=RuntimeError("PRIVATE_REDIS_PASSWORD"))
    )
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    warning = Mock()
    monkeypatch.setattr(infra.logger, "warning", warning)
    result = infra.build_infra(SimpleNamespace(pg=object(), redis=SimpleNamespace(enabled=True)))
    assert result.redis_client is None
    warning.assert_called_once_with(
        "integration initialization failed",
        extra={"component": "redis", "failure_code": "initialization_failed"},
    )
    assert "PRIVATE" not in str(warning.call_args_list)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("PRIVATE"), "timeout"),
        (PermissionError("PRIVATE"), "permission"),
        (OSError("PRIVATE"), "transport"),
        (ValueError("PRIVATE"), "invalid"),
        (type("PRIVATE_EXCEPTION_CLASS", (Exception,), {})("PRIVATE"), "internal"),
    ],
)
def test_storage_diagnostics_never_project_exception_class_names(error, expected):
    from service.infrastructure.storage.minio_file_storage import _error_code

    assert _error_code(error) == expected


@pytest.mark.parametrize("backend", ["minoi", "PRIVATE_CREDENTIAL"])
def test_worker_rejects_unknown_backend_without_local_fallback(monkeypatch, backend):
    from service.infrastructure.storage import local_file_storage
    from service.services.chat.infrastructure.chat_worker.factory import build_file_service

    local = Mock()
    monkeypatch.setattr(local_file_storage, "LocalFileStorage", local)
    with pytest.raises(StorageConfigurationError) as caught:
        build_file_service(SimpleNamespace(storage=SimpleNamespace(backend=backend)), object())
    assert caught.value.code == "storage_config_invalid"
    local.assert_not_called()


def test_worker_storage_initialization_failure_is_bounded(monkeypatch):
    from service.infrastructure.storage import local_file_storage, minio_file_storage
    from service.services.chat.infrastructure.chat_worker.factory import build_file_service

    local = Mock()
    monkeypatch.setattr(local_file_storage, "LocalFileStorage", local)
    monkeypatch.setattr(
        minio_file_storage,
        "MinioFileStorage",
        Mock(side_effect=RuntimeError("PRIVATE_WORKER_STORAGE_CREDENTIAL")),
    )
    with pytest.raises(StorageConfigurationError) as caught:
        build_file_service(
            SimpleNamespace(storage=SimpleNamespace(backend="minio"), minio=object()), object()
        )
    assert caught.value.code == "storage_init_failed"
    assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
    local.assert_not_called()
