from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_WORKER_REDIS_TIMEOUT_SEC = 2.0


@dataclass(slots=True)
class ChatWorkerDependencyFactory:
    def create_pg_connector(self, config: Any):
        from service.infrastructure.database.postgresql import PgConnector

        return PgConnector(config.pg)

    def create_redis_client(self, config: Any):
        if not config.redis or not config.redis.enabled:
            return None
        import redis as redis_sync

        return redis_sync.Redis(
            host=config.redis.host,
            port=config.redis.port,
            db=config.redis.db,
            password=config.redis.password or None,
            decode_responses=True,
            socket_timeout=_WORKER_REDIS_TIMEOUT_SEC,
            socket_connect_timeout=_WORKER_REDIS_TIMEOUT_SEC,
        )


def build_file_service(config: Any, pg_connector: Any):
    """FileSaverService с хранилищем по конфигу (minio | локальный диск).

    Живёт в НЕЙТРАЛЬНОМ модуле (не в chat_worker_tasks): агентский слой
    (`domain/tools/duckdb_client`) тоже строит файл-сервис, а импорт из
    chat_worker_tasks давал import-цикл agents→chat→agents. Здесь зависимости
    только на `service.services.files` + `service.infrastructure.storage` (без agents).
    """
    from service.composition.storage import build_file_storage
    from service.services.files.application.file_saver_service import FileSaverService
    from service.services.files.persistence.file_repository import FileRepository

    storage = build_file_storage(config)

    return FileSaverService(
        repository=FileRepository(pg_connector), folder_name="uploads", file_storage=storage
    )
