"""Resolve one configured persistence backend without cross-backend fallback."""

from __future__ import annotations

from typing import Any

from service.settings import Config


class StorageConfigurationError(RuntimeError):
    """Startup diagnostic excludes credentials, endpoints and library exceptions."""

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if code in {"storage_config_invalid", "storage_init_failed"}
            else ("storage_init_failed")
        )
        super().__init__(self.code)


def build_file_storage(config: Config) -> Any:
    # Empty is the established legacy local default. A nonempty typo is not an
    # instruction to use a different backend or a host filesystem.
    backend = str(config.storage.backend or "local").strip().lower()
    if backend not in {"local", "minio"}:
        raise StorageConfigurationError("storage_config_invalid")
    try:
        if backend == "minio":
            from service.infrastructure.storage.minio_file_storage import MinioFileStorage

            return MinioFileStorage(config.minio)
        from service.infrastructure.storage.local_file_storage import LocalFileStorage

        return LocalFileStorage()
    except Exception:
        # Do not chain raw configuration/SDK exceptions into startup diagnostics.
        # Changing the durable backend would strand existing UserFile records and
        # could falsely acknowledge uploads to a different storage lifetime.
        raise StorageConfigurationError("storage_init_failed") from None
