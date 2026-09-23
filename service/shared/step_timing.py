"""Тайминги шагов прогона и счётчик провайдерских вызовов.

⚠️ ЗАЧЕМ. У сайдкара не было НИ ОДНОГО замера времени по шагам конвейера: единственный
`perf_counter` во всём сервисе стоял в клиенте соседей (`infrastructure/sidecar.py`). То
есть любое утверждение «стало быстрее» проверить было нечем, а «мы случайно добавили
пятый служебный LLM-вызов» — тем более незаметно.

Отчёт уезжает в `metadata.timings` рядом с уже существующим `metadata.context`
(`domain/pipeline/context_assembler.py::as_meta`) — тем же каналом, что и занятость окна,
поэтому виден в трейсе без единой новой ручки.

ContextVar, а не аргумент: считать надо в мультипровайдерном слое, куда ссылку на запрос
не дотянуть, — тот же приём, что у `provider_policy_context` и `agent_settings`. У каждой
asyncio-задачи свой контекст, поэтому параллельные прогоны не путают счётчики.

⚠️ ВНЕ ПРОГОНА СБОР ВЫКЛЮЧЕН. Нет активного `collect()` — все функции ничего не делают и
ничего не аллоцируют. Это важно: `/v1`-шлюз зовут memos/ldr/graphify по чужому протоколу,
и навешивать на них сбор незачем.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any


@dataclass
class Timings:
    """Сколько времени занял каждый шаг и сколько раз ходили к провайдеру."""

    steps_ms: dict[str, float] = field(default_factory=dict)
    llm_calls: int = 0
    # Отдельно от `llm_calls`: список моделей нужен, чтобы в трейсе было видно, что
    # служебные шаги ушли НЕ на модель пользователя (компрессор и часть субагентов берут
    # свою дешёвую — см. `subagents/utils.py::pick_text_model`).
    llm_models: dict[str, int] = field(default_factory=dict)

    def add(self, step: str, elapsed_ms: float) -> None:
        # Суммируем, а не перезаписываем: шаг может выполняться несколько раз за прогон
        # (раунды инструментов, секции контекста), и интересна общая доля.
        self.steps_ms[step] = round(self.steps_ms.get(step, 0.0) + elapsed_ms, 1)

    def as_meta(self) -> dict[str, Any]:
        """Компактный отчёт для metadata ответа."""
        return {
            "steps_ms": dict(self.steps_ms),
            "llm_calls": self.llm_calls,
            "llm_models": dict(self.llm_models),
            "total_ms": round(sum(self.steps_ms.values()), 1),
        }


_CURRENT: ContextVar[Timings | None] = ContextVar("gpthub_step_timings", default=None)


@contextmanager
def collect():
    """Включить сбор на время прогона. Отдаёт `Timings`, который потом уедет в metadata."""
    timings = Timings()
    token = _CURRENT.set(timings)
    try:
        yield timings
    finally:
        _CURRENT.reset(token)


def current() -> Timings | None:
    """Активный сборщик или `None` вне прогона."""
    return _CURRENT.get()


@contextmanager
def step(name: str):
    """Замерить один шаг конвейера.

    Вне прогона (`collect()` не активен) — пустая обёртка без замера и без аллокаций.
    """
    timings = _CURRENT.get()
    if timings is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        timings.add(name, (time.perf_counter() - started) * 1000)


def count_llm_call(model: str | None = None) -> None:
    """Отметить ОДИН провайдерский вызов.

    ⚠️ Зовётся из ОДНОГО места на путь — `client/chat.py` и `client/streaming.py`, — а не
    из вызывающих. Считать у вызывающих значило бы, что новый путь к провайдеру можно
    завести мимо счётчика, и бюджет вызовов перестал бы что-либо гарантировать ровно
    тогда, когда он нужнее всего.
    """
    timings = _CURRENT.get()
    if timings is None:
        return
    timings.llm_calls += 1
    key = str(model or "?")
    timings.llm_models[key] = timings.llm_models.get(key, 0) + 1


def measure(name: str):
    """Декоратор шага конвейера: `@measure("routing")` над async-функцией.

    ⚠️ ДЕКОРАТОР, А НЕ `with` У ВЫЗЫВАЮЩЕГО, и это не вкусовщина. Первая попытка обернула
    вызовы прямо в `process_message_stream` — и страж сложности справедливо покраснел:
    пять `with` подряд вырастили худшую функцию проекта с 305 до 310 строк и со
    сложности 33 до 38. Инструментирование не должно ухудшать то, что измеряет.

    Заодно так правильнее по смыслу: имя шага принадлежит самому шагу, а не тому, кто
    его позвал. Добавить новый замер теперь можно, не трогая god-функцию.
    """

    def _decorate(fn):
        @wraps(fn)
        async def _wrapped(*args, **kwargs):
            with step(name):
                return await fn(*args, **kwargs)

        return _wrapped

    return _decorate
