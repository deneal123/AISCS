"""Драйверы вычислений. Выбор — по имени, чтобы замена рантайма была настройкой."""

from __future__ import annotations

from drivers.base import (
    ComputeDriver,
    ContainerRef,
    DriverError,
    ExecResult,
    IsolationUnverified,
    ManagedContainer,
)
from drivers.docker_cli import DRIVER_NAME as DOCKER_DRIVER
from drivers.docker_cli import DockerCliDriver

_DRIVERS = {DOCKER_DRIVER: DockerCliDriver}

__all__ = [
    "DOCKER_DRIVER",
    "ComputeDriver",
    "ContainerRef",
    "DockerCliDriver",
    "DriverError",
    "ExecResult",
    "IsolationUnverified",
    "ManagedContainer",
    "build_driver",
    "driver_names",
]


def driver_names() -> list[str]:
    return sorted(_DRIVERS)


def build_driver(name: str) -> ComputeDriver:
    """Драйвер по имени. Неизвестное имя — ОШИБКА, а не молчаливый docker.

    ⚠️ Фолбэк на умолчание здесь был бы дырой: опечатка в настройке дала бы рантайм слабее
    заказанного, и узнать об этом было бы неоткуда.
    """
    try:
        return _DRIVERS[str(name or "").strip()]()
    except KeyError:
        raise ValueError(
            f"неизвестный драйвер {name!r}; известные: {', '.join(driver_names())}"
        ) from None
