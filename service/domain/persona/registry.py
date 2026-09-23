"""Реестр личностей: JSON из админ-overlay → проверенные `PersonaSpec`.

⚠️ ЗАГРУЗЧИК ТОТАЛЬНЫЙ: он НИКОГДА не бросает наружу. Реестр редактируется руками в
админке, то есть источник заведомо ненадёжен, а прогон пользователя не должен падать
из-за чужой опечатки. Битая личность отбрасывается с WARNING, ОСТАЛЬНЫЕ работают —
деградация частичная и видимая, а не «всё или ничего».

Та же fail-open поза, что у `_SnapshotProvider` в `shared/agent_settings.py`.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from service.domain.persona.lens import PersonaLens
from service.domain.persona.schema import PersonaSpec, resolve_bundle
from service.shared.agent_settings import runtime_settings

logger = logging.getLogger(__name__)


def _raw_registry() -> Any:
    """Сырой реестр из overlay админки (с фолбэком на конфиг).

    ⚠️ `config` импортируется ЛОКАЛЬНО: пакет настроек читает поставляемые личности из
    `persona/seed.py`, то есть тянет этот пакет. Импорт настроек на уровне модуля замкнул
    бы круг (настройки → домен → настройки) и уронил бы старт сервиса.
    """
    from service.settings import config

    return runtime_settings.get_agents("personas", config.agents.personas)


def load_specs() -> dict[str, PersonaSpec]:
    """Все объявленные личности, прошедшие валидацию: `{id: spec}`."""
    raw = _raw_registry()
    if not isinstance(raw, dict):
        if raw:
            logger.warning("реестр личностей не словарь (%s) — игнорирую", type(raw).__name__)
        return {}

    specs: dict[str, PersonaSpec] = {}
    for key, body in raw.items():
        if not isinstance(body, dict):
            logger.warning("личность '%s' не объект — пропускаю", key)
            continue
        try:
            # `id` из ключа, если внутри не указан: реестр — словарь, дублировать имя
            # руками значит однажды разъехаться.
            spec = PersonaSpec(**{"id": str(key), **body})
        except ValidationError:
            logger.warning("persona definition rejected code=invalid")
            continue
        specs[spec.id] = spec
    return specs


def build_lens(persona_ids: list[str] | None, *, switched: bool = False) -> PersonaLens:
    """Собрать линзу прогона по выбору пользователя.

    Неизвестный id НЕ роняет прогон: фронт может быть новее реестра (или админ убрал
    личность, пока сообщение летело). Отбрасываем с записью в лог и работаем дальше —
    ответ без специализации лучше ошибки.

    `switched` — роль сменилась по сравнению с прошлым ответом треда; считает сторона
    вызова (только у неё есть история). Пробрасывается в линзу и в пустом случае тоже:
    снятие личности — тоже смена роли, и разрыв там нужен ровно так же.
    """
    wanted = [str(pid).strip() for pid in (persona_ids or []) if str(pid).strip()]
    if not wanted:
        return PersonaLens(switched=switched)

    available = load_specs()
    chosen: list[PersonaSpec] = []
    for pid in wanted:
        spec = available.get(pid)
        if spec is None:
            logger.info("персона '%s' не найдена в реестре — пропускаю", pid)
            continue
        if not spec.enabled:
            logger.info("персона '%s' выключена в реестре — пропускаю", pid)
            continue
        chosen.append(spec)

    return PersonaLens(resolve_bundle(chosen), switched=switched)


def catalog() -> list[dict[str, Any]]:
    """Каталог для интерфейса: что вообще можно выбрать."""
    return [
        {"id": s.id, "label": s.label, "hint": s.hint}
        for s in sorted(load_specs().values(), key=lambda s: (s.priority, s.id))
        if s.enabled
    ]
