"""Пустая строка из compose означает «не задано», а не «пустое значение».

⚠️ compose отдаёт около шестидесяти переменных как `"${VAR:-}"`, и незаданная приезжает как
`""`, а не отсутствует. `int`/`float`/`bool` на пустой строке падают, поэтому одна убранная
строка из `.env` роняла бы конструирование конфига целиком. У строк пустота осмысленна
(«ключ не задан») — их не трогаем.

Раньше валидатор был скопирован в оба класса настроек дословно.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationInfo, field_validator


class EmptyStringMeansUnset(BaseModel):
    """Примесь: приводит пустую строку к дефолту поля для нестроковых типов."""

    @field_validator("*", mode="before")
    @classmethod
    def _empty_string_means_unset(cls, value: Any, info: ValidationInfo) -> Any:
        if value != "":
            return value
        field = cls.model_fields.get(info.field_name)
        if field is None:
            return value
        if field.annotation in (str, "str") or field.annotation is None:
            return value
        default = field.default
        if default is not None and str(type(default)) != "<class 'PydanticUndefinedType'>":
            return default
        factory = getattr(field, "default_factory", None)
        return factory() if callable(factory) else value
