# ruff: noqa: E501 — плотная декларативная таблица настроек, длинные строки осознанны.
"""Реестр редактируемых runtime-настроек (whitelist).

Это ЕДИНСТВЕННАЯ поверхность, которую можно читать/писать через overlay и
админ-API. Секреты (ключи/пароли/токены) сюда НЕ вносятся → они недоступны для
правки из UI ни при каких условиях. Каждый ключ — dotted-путь `section.field`,
section/field выводятся из ключа и маппятся на `config.<section>.<field>`.
"""

from __future__ import annotations

# Форма спеки — в отдельном модуле: таблицы разъехались по файлам (реестр перерос лимит
# размера), и общий дом для `SettingSpec`/`_s` не даёт им импортировать друг друга по кругу.
# Имена ре-экспортируются: их импортируют из этого модуля исторически.
from service.services.admin.application.settings.agents import _AGENTS
from service.services.admin.application.settings.billing import _BILLING
from service.services.admin.application.settings.spec import SettingSpec, SettingType, _s

__all__ = ["REGISTRY", "SettingSpec", "SettingType", "all_specs", "coerce_strict", "get_spec"]


# --- Подтверждение email (config.email) — только НЕ-секретные ручки OTP.
# Секреты (host/login/password/from_address) правятся ТОЛЬКО через env.
_MAIL: list[SettingSpec] = [
    _s(
        "email.code_length",
        "Почта",
        "int",
        "Длина кода",
        "Сколько цифр в коде подтверждения email.",
        4,
        8,
    ),
    _s(
        "email.code_ttl_seconds",
        "Почта",
        "int",
        "TTL кода (сек)",
        "Сколько секунд действует код подтверждения, прежде чем истечёт.",
        60,
        3600,
    ),
]

REGISTRY: dict[str, SettingSpec] = {s.key: s for s in (*_BILLING, *_AGENTS, *_MAIL)}


def get_spec(key: str) -> SettingSpec | None:
    return REGISTRY.get(key)


def all_specs() -> list[SettingSpec]:
    return list(REGISTRY.values())


def _clamp(value: float, spec: SettingSpec) -> float:
    if spec.minimum is not None:
        value = max(value, spec.minimum)
    if spec.maximum is not None:
        value = min(value, spec.maximum)
    return value


def coerce_strict(spec: SettingSpec, raw):
    """Привести значение к типу настройки с клампом; ValueError при несовместимости.

    Используется при записи через админ-API (невалидный ввод → 422, не молчаливый
    дефолт как при чтении).
    """
    t = spec.type
    if t == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in {"true", "1", "yes", "on"}:
            return True
        if s in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"{spec.key}: expected bool")
    if t == "int":
        return int(_clamp(int(raw), spec))
    if t == "float":
        return float(_clamp(float(raw), spec))
    if t == "str":
        return str(raw)
    if t == "json":
        if isinstance(raw, (dict, list)):
            return raw
        raise ValueError(f"{spec.key}: expected JSON object/array")
    raise ValueError(f"{spec.key}: unknown type {t}")
