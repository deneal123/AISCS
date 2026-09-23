"""Форма одной редактируемой настройки — общая для всех таблиц реестра.

Вынесено из `settings_registry.py`, когда тот перерос лимит размера и часть таблиц
переехала в соседние модули: без общего дома для `SettingSpec`/`_s` они импортировали бы
друг друга по кругу.

Правила, действующие для ЛЮБОЙ таблицы:
* ключ — dotted-путь `section.field`, и он ЕДИНСТВЕННЫЙ источник: секция и поле выводятся
  из него, а не задаются отдельно (два независимых имени однажды разъезжаются);
* секреты (ключи/пароли/токены) в реестр НЕ вносятся — иначе их можно было бы прочитать и
  переписать через админ-API;
* «редактируемых no-op» не бывает: если ключ объявлен, он обязан реально читаться через
  overlay, иначе тумблер в панели декоративный (это стережёт офлайн-гейт контракта).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SettingType = Literal["bool", "int", "float", "str", "json"]


@dataclass(frozen=True)
class SettingSpec:
    key: str  # "billing.margin_multiplier"
    group: str  # отображаемая группа в UI
    type: SettingType
    section: str  # config sub-object: "billing" | "agents"
    field: str  # имя поля в config-секции
    label: str
    minimum: float | None = None
    maximum: float | None = None
    description: str = ""  # человекопонятное объяснение, что меняет настройка


def _s(key, group, type_, label, desc="", lo=None, hi=None) -> SettingSpec:
    section, field = key.split(".", 1)  # section/field — единый источник: ключ
    return SettingSpec(key, group, type_, section, field, label, lo, hi, desc)
