"""Роутинг-решение: какой моделью и каким агентом обрабатывать запрос.

Живёт в сайдкаре, потому что роутер — это ЛЛМ-вызов, а решать «какой моделью»
должен тот, кто владеет провайдерами и знает, какие модели вообще доступны.

История: при переезде домена в сабмодуль этот модуль не поехал, и `POST /route`
отвечал 503 на КАЖДЫЙ запрос — backend ловил ошибку и отправлял сообщение вообще
без роутинга. Восстановлен из версии backend'а, из которой убрано лишнее:
`_resolve_via_sidecar` (здесь это была бы рекурсия сайдкар→сайдкар) и
`ModelRoutingError` (тянет chat-иерархию исключений backend'а — за границей
сервиса ошибка отдаётся кодом ответа, а не чужим классом).
"""

from __future__ import annotations

import logging

from service.application.route_contracts import ChatRouteDecision
from service.domain.routing.policy import canonical_route
from service.domain.run_context import RunExecutionContext
from service.domain.usage_ledger import UsageKind

logger = logging.getLogger(__name__)

# Инструменты, которые роутер выражает через route_override, а не через отдельный флаг.
_OVERRIDE_TOOLS = frozenset({"audio_transcribe", "image_gen", "pdf_gen", "general"})


class ModelRoutingError(RuntimeError):
    """Роутер не смог принять решение. На границе сервиса маппится в 502."""


class ModelRoutingService:
    async def resolve_route(
        self,
        text: str,
        selected_model: str | None,
        input_type: str | None,
        web_search: bool,
        deep_research: bool,
        route_override: str | None,
        execution: RunExecutionContext,
    ) -> ChatRouteDecision:
        from service.domain.tools.router import route_model

        try:
            effective_model, routing_meta = await route_model(
                text=text,
                selected_model=selected_model,
                input_type=input_type,
                execution=execution,
            )
        except Exception as exc:  # noqa: BLE001
            raise ModelRoutingError("Failed to resolve model route") from exc

        resolved_web_search = web_search
        resolved_deep_research = deep_research
        resolved_route_override = canonical_route(route_override)
        resolved_category: str | None = None

        # Явный выбор пользователя приоритетнее авто-решения: авто-инструмент
        # применяем, только когда пользователь ничего не потребовал сам.
        if not web_search and not deep_research and not route_override:
            auto_tool = routing_meta.get("tool", "none")
            # audio_transcribe — только при реальном аудио-входе (защита в глубину
            # поверх _guard_tool_modality в route_model): текстовый/документный
            # файл не должен принудительно уходить на ASR-агент.
            if auto_tool == "audio_transcribe" and input_type != "audio":
                auto_tool = "general"
            if auto_tool == "web_search":
                resolved_web_search = True
            elif auto_tool == "deep_research":
                resolved_deep_research = True
            elif auto_tool in _OVERRIDE_TOOLS:
                resolved_route_override = auto_tool
            # ⚠️ `"tool" in routing_meta`, А НЕ ПРОСТО `auto_tool == "none"`. В ручном
            # режиме `route_model` короткозамыкается в `source:"manual"` БЕЗ LLM-вызова и
            # без ключа `tool` — а `.get("tool", "none")` выше подставляет туда «none» по
            # умолчанию. Без этой проверки мы подсказывали бы категорию там, где
            # авто-роутер не звался ВООБЩЕ, то есть подменяли бы единственный роутинг
            # своей догадкой. Поймано тестом, не размышлением.
            elif auto_tool == "none" and "tool" in routing_meta:
                # ⚠️ ЗДЕСЬ СНИМАЕТСЯ ВТОРОЙ LLM-РОУТИНГ. «none» у этого роутера значит
                # «отдельный инструментальный маршрут не требуется» — то же самое, что
                # «general» у роутера внутри `/run`, у которого другого варианта «без
                # инструмента» попросту нет (его набор — строгое подмножество нашего).
                #
                # Раньше `route_override` оставался пустым, и `/run` звал роутер заново по
                # ТОМУ ЖЕ тексту. Причём второй роутер видит МЕНЬШЕ: только текст, без
                # `input_type` и без списка моделей. А на MWS (провайдер по умолчанию) он
                # вызывает ту же самую функцию `route_model` — то есть буквально повторяет
                # этот вызов. Второе мнение это не давало, минус один полный
                # провайдерский вызов и 300-1500 мс до первого токена — давало.
                resolved_category = "general"

        return ChatRouteDecision(
            selected_model=effective_model,
            routing_metadata=dict(routing_meta or {}),
            web_search=resolved_web_search,
            deep_research=resolved_deep_research,
            route_override=resolved_route_override,
            # usage роутер-ЛЛМ: по нему воркер ОТДЕЛЬНО тарифицирует пользователя.
            # Потеряем — вызов достанется бесплатно. Пусто в ручном режиме
            # (роутер-ЛЛМ не звался).
            # ⚠️ Здесь стояло `if routing_usage.get("total")`, а `/run` для ТОГО ЖЕ вызова
            # смотрел на prompt/completion. Провайдер, не заполняющий `total_tokens`,
            # терял тарификацию роутинга на этом пути и сохранял на том.
            routing_usage=execution.usage.as_token_usage(kind=UsageKind.ROUTE_MODEL.value)
            if execution.usage.has_kind(UsageKind.ROUTE_MODEL.value)
            else {},
            resolved_category=resolved_category,
        )
