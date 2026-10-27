"""Контракт решения авто-оркестратора: что он возвращает и как это чинится.

Сегодняшний «Авто» — классификатор на ОДНУ метку: он выбирает ровно одну категорию из
пяти и не решает ничего больше. Планирование и мульти-интент — ручные тумблеры человека,
причём `multi_intent_enabled` по умолчанию выключен, то есть в «Авто» декомпозиция не
работает почти никогда. Оркестратор отвечает на НАБОР вопросов одним вызовом.

🔴 `route` — это «что нужно», а не «что запускаем»: право потратить деньги остаётся у
политики, не у модели. Дорогой режим стоит до 2500 кредитов.

Ни клиента, ни SDK — решение проверяется без единого мока провайдера.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from service.domain.capabilities import route_vocabulary

# Три значения, а не число: числу от модели верить нельзя, а порог пришлось бы
# подбирать. Важна одна граница — «явная просьба» против «вывода по контексту».
CONFIDENCE_HIGH = "high"
CONFIDENCE_LEVELS = ("low", "medium", CONFIDENCE_HIGH)
_DEFAULT_CONFIDENCE = "low"

# Ставим МЫ, не модель: спрашивать у неё, вызывали ли её, бессмысленно.
SOURCE_SHORTCUT = "shortcut"
SOURCE_LLM = "llm"

REASON_SHORTCUT_EMPTY = "shortcut_empty"
REASON_SHORTCUT_SMALLTALK = "shortcut_smalltalk"
REASON_SHORTCUT_CONTINUE = "shortcut_continue"
REASON_MODEL_CLASSIFICATION = "model_classification"


@dataclass(frozen=True, slots=True)
class AutoDecision:
    """Решение оркестратора. `route=None` — «маршрут не мой, решай как раньше»."""

    route: str | None = None
    confidence: str = _DEFAULT_CONFIDENCE
    needs_fresh_data: bool = False
    # 🔴 Нужны ли инструменты работы с файлами. Шесть схем `ws_*` стоят токенов в КАЖДОМ
    # запросе, а любой их вызов гонит весь контекст (включая вложение) вторым кругом.
    # Живой замер: «прочитай файл и сделай саммери» стоил 38k токенов вместо 19k, потому
    # что модель полезла в песочницу за документом, который уже лежал у неё в контексте.
    needs_files: bool = False
    needs_plan: bool = False
    multi_step: bool = False
    # Это код нашей policy, а не свободное объяснение модели. Его можно безопасно передать
    # в trace и сохранить в confirmation metadata.
    reason_code: str = REASON_MODEL_CLASSIFICATION
    source: str = SOURCE_LLM

    def with_source(self, source: str) -> AutoDecision:
        return replace(self, source=source)


def _as_bool(value: Any) -> bool:
    """Булево из ответа модели; всё непонятное → False.

    ⚠️ Консервативно в сторону «не тратить»: `True` означает списанные кредиты. Не смогла
    вернуть булево — доверия к решению тоже нет.
    """
    return value is True


def normalize_decision(raw: Any) -> AutoDecision | None:
    """Сырой ответ модели → решение. `None` — «не разобрали, работай как раньше».

    🔴 Деградация ПОФИЛЬНАЯ: непонятный `route` не отменяет разобранные стратегии —
    маршрут отдаём старому роутеру, план остаётся. Иначе платили бы лишним вызовом там,
    где ответ годен на восемь десятых.

    ⚠️ `audio_transcribe` отбрасываем: он форсится по типу вложения, а выбранный по тексту
    уводит запрос от файла, которого не прикладывали.
    """
    if not isinstance(raw, dict):
        return None

    from service.domain.routing.policy import canonical_route

    route = canonical_route(raw.get("route"))
    if not isinstance(route, str) or route not in route_vocabulary():
        route = None

    confidence = raw.get("confidence")
    if not isinstance(confidence, str) or confidence not in CONFIDENCE_LEVELS:
        # Мусор → low: высокая уверенность короткозамыкает ответ, низкая — нет.
        confidence = _DEFAULT_CONFIDENCE

    return AutoDecision(
        route=route,
        confidence=confidence,
        needs_fresh_data=_as_bool(raw.get("needs_fresh_data")),
        needs_files=_as_bool(raw.get("needs_files")),
        needs_plan=_as_bool(raw.get("needs_plan")),
        multi_step=_as_bool(raw.get("multi_step")),
        reason_code=REASON_MODEL_CLASSIFICATION,
        source=SOURCE_LLM,
    )
