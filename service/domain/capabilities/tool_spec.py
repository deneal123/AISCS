"""Декларация инструмента и ТИПИЗИРОВАННЫЙ отказ в его выдаче.

⚠️ ЗАЧЕМ ОТКАЗ ОТДЕЛЬНЫМ ПОНЯТИЕМ. Раньше инструмент, которому не с чем работать, просто
исчезал из списка. Снаружи это неотличимо от «модель решила им не пользоваться»: человек
видит уверенный ответ по памяти вместо поиска и не знает, что поиска не было. Тем же
молчанием отвечал и провал каталога моделей — инструменты снимались со ВСЕХ моделей, и
единственным следом оставалась строка в логе.

Отказ — это часть ответа, а не его отсутствие. Причина типизирована, потому что «не выдан»
и «не смогли выяснить, умеет ли модель» требуют РАЗНЫХ действий: первое нормально, второе
означает, что сломан каталог.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_spec import COST_CHEAP, COST_CLASSES, COST_EXPENSIVE

EFFECT_READ_ONLY = "read_only"
EFFECT_WORKSPACE_MUTATION = "workspace_mutation"
EFFECT_EXTERNAL_MUTATION = "external_mutation"
TOOL_EFFECTS = frozenset({EFFECT_READ_ONLY, EFFECT_WORKSPACE_MUTATION, EFFECT_EXTERNAL_MUTATION})

GROUNDING_WORKSPACE = "workspace"
GROUNDING_REPOSITORY = "repository"
GROUNDING_FRESH_DATA = "fresh_data"
GROUNDING_TABULAR = "tabular"
GROUNDING_ROLES = frozenset(
    {
        GROUNDING_WORKSPACE,
        GROUNDING_REPOSITORY,
        GROUNDING_FRESH_DATA,
        GROUNDING_TABULAR,
    }
)

# Закрытый словарь причин. Новый источник инструментов (MCP, workspace) добавляет СВОЮ
# причину сюда, а не пишет произвольную строку: иначе разбирать их станет нечем.
MISSING_DATA = "missing_data"  # нет данных, с которыми инструмент работает
DISABLED_BY_CONFIG = "disabled_by_config"  # выключен настройкой
MODEL_NO_TOOL_SUPPORT = "model_no_tool_support"  # модель не умеет function-calling
CATALOG_UNKNOWN = "catalog_unknown"  # 🔴 НЕ ЗНАЕМ, умеет ли: каталог недоступен
NEEDS_CONFIRMATION = "needs_confirmation"  # дорогой инструмент, человек не подтверждал
NOT_IN_TIER = "not_in_tier"  # отложен прогрессивным раскрытием, может появиться следующим раундом
OMISSION_REASONS = (
    MISSING_DATA,
    DISABLED_BY_CONFIG,
    MODEL_NO_TOOL_SUPPORT,
    CATALOG_UNKNOWN,
    NEEDS_CONFIRMATION,
    NOT_IN_TIER,
)

# Потолок результата инструмента по умолчанию. Результат переотправляется КАЖДЫМ следующим
# раундом: ответ `analyze_data` на 11 813 символов ехал в промпте четырежды.
DEFAULT_RESULT_LIMIT = 6000

# Потолок времени на ОДИН вызов инструмента. Щедрый: сайдкар DuckDB бюджетирует 60 с сам,
# веб-поиск перебирает до пяти движков. Реально ограничивает не он, а остаток бюджета
# прогона — см. `shared/deadline`.
DEFAULT_TOOL_TIMEOUT_SEC = 90.0


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Одна декларация инструмента. Всё производное выводится отсюда."""

    name: str
    tool: Any  # объект FunctionTool: `.name`, `.description`, `.params_json_schema`

    # Поле `UserContext`, без которого инструменту нечего делать. `None` — выдаётся всегда.
    # ⚠️ Гейт СТРУКТУРНЫЙ, а не по статистике: «редко зовут» — плохое основание убирать
    # инструмент, а «работать не с чем» проверяется точно и ничего не отнимает.
    requires_context_attr: str | None = None
    # Имя надбавки в `contracts.BILLABLE_TOOLS`. `None` — вызов не тарифицируется отдельно.
    billing_name: str | None = None
    # Потолок результата. `None` — НЕ резать: для канонических чтений (файл, документ)
    # молча обрезанный результат это неверный результат, а не короткий.
    result_limit_chars: int | None = DEFAULT_RESULT_LIMIT
    default_timeout_sec: float = DEFAULT_TOOL_TIMEOUT_SEC
    # Имя булева поля `AgentsConfig`, выключающего инструмент.
    enabled_field: str | None = None
    # Откуда инструмент: родной, из MCP-сервера, из workspace. Разные источники приходят в
    # ОДИН резолвер и получают один гейт, лимиты и биллинг.
    source: str = "native"
    # Короткое назначение для selector-а. В manifest никогда не попадает JSON-схема
    # инструмента: она нужна основной модели, но на большом MCP-наборе вытесняет контекст.
    # Пустое значение допустимо для внешнего MCP: тогда берём безопасно усечённое описание.
    selector_hint: str = ""
    # Разрешено ли в пределах ОДНОГО run переиспользовать результат точного повторного
    # вызова. Значение намеренно deny-by-default: новый MCP-инструмент может менять
    # внешнее состояние, и один лишь совпавший JSON не делает его безопасным для reuse.
    # Workspace тоже остаётся выключенным: даже read-инструмент может увидеть изменение,
    # сделанное предыдущим шагом того же run.
    dedup_safe: bool = False
    # Execution ordering is policy too. Calls in one non-empty concurrency group are
    # serialized in model order; ungrouped read-only calls retain bounded parallelism.
    effect: str = EFFECT_READ_ONLY
    concurrency_group: str | None = None
    # Trusted static roles used only when deterministic grounding is required and
    # selection degraded without a preferred tool. Names and prefixes are not policy.
    grounding_roles: frozenset[str] = frozenset()

    # --- деньги ------------------------------------------------------------ #
    # 🔴 КЛАСС ЦЕНЫ ЕСТЬ У МАРШРУТА, НО НЕ БЫЛО У ИНСТРУМЕНТА — а инструмент бывает дорог
    # как маршрут. Просмотр часового видео — это сотня кадров (десятки тысяч токенов
    # изображений) плюс расшифровка, и всё это переезжает в КАЖДОЕ следующее сообщение
    # треда. Инструмент вызывает МОДЕЛЬ, посреди прогона, без единого вопроса человеку —
    # значит без объявленного класса цены дорогая способность тратила бы деньги без спроса.
    #
    # Словарь ОБЩИЙ с `AgentSpec` (`COST_*` импортированы, не переписаны): два независимых
    # перечня «дёшево/платно/дорого» разошлись бы, и гейт подтверждения стал бы решать по
    # разным шкалам для маршрута и для инструмента.
    cost_class: str = COST_CHEAP
    # Дорогой инструмент не выдаётся, пока человек не согласился. Согласие приезжает
    # ПРИЗНАКОМ В КОНТЕКСТЕ (как `web_tool_enabled`/`workspace_tools_enabled`), а не новой
    # машинерией: предложение кнопкой у нас уже есть, и второе рядом с ним разошлось бы.
    confirm_by_default: bool = False

    def __post_init__(self) -> None:
        if self.effect not in TOOL_EFFECTS:
            raise ValueError(f"{self.name}: неизвестный эффект инструмента {self.effect!r}")
        if set(self.grounding_roles) - GROUNDING_ROLES:
            raise ValueError(f"{self.name}: unknown grounding roles")
        if self.cost_class not in COST_CLASSES:
            raise ValueError(f"{self.name}: неизвестный класс цены {self.cost_class!r}")
        # 🔴 ДОРОГОЙ ИНСТРУМЕНТ ОБЯЗАН БЫТЬ ЗАПЕРТ ПРИЗНАКОМ. Объявить цену и оставить
        # инструмент в наборе — это ровно «тратить деньги без спроса»: модель зовёт его
        # сама, посреди прогона, и спросить в этот момент уже некого. Проверка стоит
        # ЗДЕСЬ, в конструкторе, потому что забыть признак можно только один раз — при
        # объявлении; тест поймал бы это позже и не везде.
        if self.cost_class == COST_EXPENSIVE and not self.requires_context_attr:
            raise ValueError(
                f"{self.name}: дорогой инструмент без `requires_context_attr` уедет модели "
                "в каждом прогоне и будет потрачен без согласия человека"
            )
        if self.confirm_by_default and not self.requires_context_attr:
            raise ValueError(
                f"{self.name}: `confirm_by_default` без `requires_context_attr` ничего не "
                "запирает — согласие человека приезжает признаком контекста"
            )


@dataclass(frozen=True, slots=True)
class Omission:
    """Инструмент не выдан модели — и вот почему."""

    tool: str
    reason: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.reason not in OMISSION_REASONS:
            raise ValueError(f"{self.tool}: неизвестная причина отказа {self.reason!r}")

    def as_meta(self) -> dict[str, str]:
        meta = {"tool": self.tool, "reason": self.reason}
        if self.detail:
            meta["detail"] = self.detail
        return meta


@dataclass(frozen=True, slots=True)
class ToolSet:
    """Что модель получила и чего не получила. Второе так же важно, как первое."""

    tools: list = field(default_factory=list)
    omissions: list[Omission] = field(default_factory=list)

    def as_meta(self) -> list[dict[str, str]]:
        return [o.as_meta() for o in self.omissions]
