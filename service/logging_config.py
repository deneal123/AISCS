"""Конфигурация логирования backend.

⚠️ Вынесено из `settings.py` осознанно: это НЕ настройка сервиса, а форма вывода, и в файле
настроек оно занимало место, которого там не хватало под настоящие поля. Импорт
`from service.settings import LOGGING` продолжает работать — фасад ре-экспортирует.
"""

from __future__ import annotations

import os

LOGGING_LEVEL = os.environ.get("SERVICE__LOGGING_LEVEL", "debug").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "default": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"},
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "level": LOGGING_LEVEL,
            "formatter": "default",
        },
    },
    "loggers": {
        "service": {
            "level": LOGGING_LEVEL,
            "handlers": ["default"],
            "propagate": False,
        },
    },
    "root": {"level": LOGGING_LEVEL, "handlers": ["default"]},
}
