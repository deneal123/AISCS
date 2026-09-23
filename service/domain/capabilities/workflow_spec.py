"""Workflow-агент: заранее объявленная последовательность шагов.

🔴 ГЛАВНОЕ ЗДЕСЬ — ЧЕГО НЕТ. Никакого движка исполнения не появляется. Workflow — это
`list[SubTask]`, объявленный заранее вместо того, чтобы каждый раз выпрашиваться у модели
декомпозицией. Исполняет его существующий `pipeline/execution_plan.execute_steps`, у
которого уже есть всё нужное: параллельность независимых шагов, передача вывода предыдущего
следующему, пере-эмит `token_usage` и артефактов списком, прогресс и финальный синтез.

Зачем тогда объявлять, если декомпозиция и так умеет: она СТОИТ вызова модели, ошибается на
знакомых сценариях и даёт разный результат на один и тот же запрос. Объявленный маршрут
детерминирован и бесплатен.

⚠️ Workflow живёт в ТОМ ЖЕ словаре маршрутов, что и агенты: оркестратор выбирает один
идентификатор и не знает, агент это или последовательность. Иначе у него появился бы второй
вопрос («а не workflow ли это?»), и цена ошибки удвоилась бы.
"""

from __future__ import annotations

from dataclasses import dataclass

from .agent_spec import COST_CHEAP, COST_CLASSES

# Подстановка запроса человека в инструкцию шага.
_PLACEHOLDER = "{user_input}"


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """Один шаг: какой агент и с какой инструкцией."""

    agent: str
    instruction: str
    # Шаг не зависит от результата предыдущих — можно исполнять параллельно.
    independent: bool = False


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    """Объявленная последовательность. Поля совпадают с `AgentSpec` там, где смысл общий."""

    name: str
    label_ru: str
    steps: tuple[WorkflowStep, ...]
    prompt_hint: str = ""
    cost_class: str = COST_CHEAP
    confirm_by_default: bool = False
    enabled_field: str | None = None

    def __post_init__(self) -> None:
        if self.cost_class not in COST_CLASSES:
            raise ValueError(f"{self.name}: неизвестный класс цены {self.cost_class!r}")
        if not self.steps:
            raise ValueError(f"{self.name}: workflow без шагов ничего не делает")

    def instantiate(self, user_input: str) -> list:
        """Развернуть в подзадачи — ровно те, что вернула бы декомпозиция.

        ⚠️ Импорт ЛОКАЛЬНЫЙ: `SubTask` живёт в конвейере, а конвейер читает реестр. На
        уровне модуля это замкнуло бы круг.
        """
        from service.domain.pipeline.decomposition import SubTask

        return [
            SubTask(
                category=step.agent,
                instruction=step.instruction.replace(_PLACEHOLDER, str(user_input or "")),
                independent=step.independent,
            )
            for step in self.steps
        ]
