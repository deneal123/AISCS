"""Flow helpers for AgentProcessor orchestration steps."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from service.domain.run_context import RunExecutionContext
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext
from service.shared import step_timing


def build_user_context(
    *,
    user_id: int | None,
    session: Any | None,
    thread_id: str,
    tabular_files: list[dict] | None = None,
    reference_image_url: str | None = None,
    repo_graph_ids: list[str] | None = None,
    has_non_tabular_attachment: bool = False,
    workspace_ref: dict | None = None,
    video_tool_enabled: bool = False,
) -> UserContext:
    """Build normalized user context for downstream agents.

    ``tabular_files`` — презайнед-ссылки на табличные файлы (собраны бэкендом): через
    контекст их видит инструмент ``analyze_data``, поэтому в сайдкаре он работает без
    доступа к PG/MinIO.
    """
    return UserContext(
        user_id=str(user_id or ""),
        request_time=datetime.now(UTC),
        session=session,
        thread_id=thread_id,
        tabular_files=tabular_files,
        reference_image_url=reference_image_url,
        repo_graph_ids=repo_graph_ids,
        has_non_tabular_attachment=has_non_tabular_attachment,
        workspace_ref=workspace_ref,
        # 🔴 СОГЛАСИЕ ЧЕЛОВЕКА НА ДОРОГОЙ ПРОСМОТР. Признак существовал в схеме контекста
        # и проверялся гейтом инструмента, но досюда не доходил НИКОГДА: контракт `/run`
        # его не вёз, а контекст собирался без него. Замер: нажатие кнопки «посмотреть
        # ролик» давало ответ «Режим „просмотр видео“ не запускался», и сайдкар video не
        # получал ни одного запроса — только health-пробы.
        video_tool_enabled=video_tool_enabled,
    )


@step_timing.measure("routing")
async def resolve_agent_route(
    *,
    orchestrator,
    user_input: str,
    thread_id: str,
    route_override: str | None,
    input_type: str | None,
    web_search: bool,
    deep_research: bool,
    execution: RunExecutionContext,
    resolved_category: str | None = None,
) -> tuple[str, AgentEvent, AgentEvent]:
    """Маршрут и события маршрутизации (без номеров последовательности).

    Usage роутера оркестратора записывается в общий run ledger. Это настоящий провайдерский
    вызов, срабатывающий почти на каждом сообщении, и до сих пор он не тарифицировался
    вовсе — ни на MWS-ветке, ни на SDK.

    ⚠️ `resolved_category` СНИМАЕТ ЭТОТ ВЫЗОВ, когда авто-роутер в `/route` уже ответил.
    Раньше тот же текст роутился ДВАЖДЫ: сначала в `/route` (backend зовёт её ради
    резерва кредитов), потом здесь. Второй роутер при этом видит МЕНЬШЕ — только текст,
    без `input_type` и без списка моделей, — а на MWS (провайдер по умолчанию) вызывает
    ту же самую функцию `route_model`. Второе мнение это не давало; минус один полный
    провайдерский вызов и 300-1500 мс до первого токена — давало.

    Пусто при ручном выборе модели: там `route_model` короткозамыкается в
    `source:"manual"` БЕЗ LLM-вызова, и этот роутер — единственный, а не дублирующий.
    """
    routing_start = AgentEvent(
        type=EventType.ROUTING_START,
        data="Определяю подходящего агента...",
    )

    # Форс важнее готового ответа: пользователь мог явно потребовать инструмент уже
    # после того, как авто-роутер сказал «не нужен».
    forced = route_override or web_search or deep_research
    if resolved_category and not forced:
        agent_name = resolved_category
    else:
        agent_name = await orchestrator.route(
            user_input,
            thread_id,
            route_override=route_override,
            input_type=input_type,
            web_search=web_search,
            deep_research=deep_research,
        )

    routing_complete = AgentEvent(
        type=EventType.ROUTING_COMPLETE,
        agent_name=agent_name,
        data=f"Выбран агент: {agent_name}",
        metadata={"agent_type": agent_name},
    )

    return agent_name, routing_start, routing_complete
