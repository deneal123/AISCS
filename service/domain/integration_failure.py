"""Closed failure contract shared by provider, MCP, and sidecar boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class IntegrationSource(StrEnum):
    MCP = "mcp"
    WORKSPACE = "workspace"
    PROVIDER = "provider"
    SIDECAR = "sidecar"
    INTERNAL = "internal"


class IntegrationFailureCode(StrEnum):
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    REMOTE = "remote"
    PROTOCOL = "protocol"
    CONFLICT = "conflict"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    CANCELLED = "cancelled"
    POLICY = "policy"
    INTERNAL = "internal"


class StatusFamily(StrEnum):
    NONE = "none"
    CLIENT = "4xx"
    SERVER = "5xx"
    TRANSPORT = "transport"


_MODEL_MESSAGES = {
    IntegrationFailureCode.TIMEOUT: (
        "Инструмент не успел завершить операцию. Продолжи без результата."
    ),
    IntegrationFailureCode.TRANSPORT: ("Интеграция временно недоступна. Продолжи без результата."),
    IntegrationFailureCode.REMOTE: (
        "Внешняя интеграция отклонила операцию. Продолжи без результата."
    ),
    IntegrationFailureCode.PROTOCOL: (
        "Интеграция вернула неподдерживаемый ответ. Продолжи без результата."
    ),
    IntegrationFailureCode.CONFLICT: (
        "Рабочая версия изменилась. Сначала перечитай данные и только затем предложи новый вызов."
    ),
    IntegrationFailureCode.EXPIRED: "Рабочая среда истекла или больше недоступна.",
    IntegrationFailureCode.UNAVAILABLE: (
        "Рабочая среда временно недоступна. Продолжи без результата."
    ),
    IntegrationFailureCode.INVALID: (
        "Операция не прошла проверку. Исправь аргументы следующего вызова."
    ),
    IntegrationFailureCode.CANCELLED: "Операция отменена.",
    IntegrationFailureCode.POLICY: "Операция запрещена политикой выполнения.",
    IntegrationFailureCode.INTERNAL: "Инструмент завершился безопасно обработанной ошибкой.",
}


@dataclass(frozen=True, slots=True)
class IntegrationFailure(Exception):
    """Failure safe for control flow; the originating exception is never retained."""

    source: IntegrationSource
    code: IntegrationFailureCode
    retryable: bool = False
    status_family: StatusFamily = StatusFamily.NONE

    @property
    def reason_code(self) -> str:
        return self.code.value

    def model_message(self) -> str:
        return _MODEL_MESSAGES[self.code]

    def bounded_metadata(self) -> dict[str, Any]:
        return {
            "failure_code": self.code.value,
            "category": self.source.value,
            "retryable": self.retryable,
            "status_family": self.status_family.value,
        }

    def __str__(self) -> str:
        return self.code.value


def status_family(status: int | None) -> StatusFamily:
    if status is None:
        return StatusFamily.NONE
    if 400 <= status < 500:
        return StatusFamily.CLIENT
    if status >= 500:
        return StatusFamily.SERVER
    return StatusFamily.NONE


__all__ = [
    "IntegrationFailure",
    "IntegrationFailureCode",
    "IntegrationSource",
    "StatusFamily",
    "status_family",
]
