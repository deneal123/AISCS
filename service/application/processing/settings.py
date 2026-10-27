"""One call-time adapter to the run's admin settings snapshot for processing stages."""

from typing import Any

from service.settings import config
from service.shared.agent_settings import runtime_settings


def _agent_flag(name: str, default: Any) -> Any:
    """Runtime-настройка агентов из админ-overlay (fail-safe → дефолт из config)."""
    return runtime_settings.get_agents(name, default)


def _orchestrator_flags() -> dict:
    """Настройки оркестратора из админ-снимка.

    Отдельно от вызова: это чтение конфигурации, а не решение о маршруте, и в теле шага оно
    мешало видеть сам конвейер.
    """
    return {
        "enabled": _agent_flag(
            "auto_orchestrator_enabled", config.agents.auto_orchestrator_enabled
        ),
        "confirm_modes": _agent_flag("auto_confirm_modes", config.agents.auto_confirm_modes),
    }
