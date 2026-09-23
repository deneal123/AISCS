"""Реестр субагентов и policy-маршрутизация.

⚠️ LLM-роутинга здесь больше НЕТ. Маршрут решает авто-оркестратор
(`domain/routing/auto_*`); сюда запрос попадает, только когда тот не участвовал — при явном
выборе человека, форсе по модальности или сбое решателя. Первые два случая это чистая
policy, а третий второй LLM-вызов всё равно не спасал: он шёл к тому же провайдеру, который
только что не справился.
"""

import logging

from service.domain.base import BaseAgent
from service.domain.routing import resolve_forced_category
from service.domain.subagents import build_subagents

logger = logging.getLogger(__name__)


class Orchestrator:
    """Держит собранных субагентов и отвечает на «кто отвечает» без вызовов модели.

    Приоритет: явный выбор человека и форс по модальности → безопасный `general`.
    """

    def __init__(self, model_settings: dict | None = None):
        self.model_settings = model_settings or {}
        self._agents: dict[str, BaseAgent] = build_subagents(self.model_settings)

    async def route(
        self,
        user_input: str,
        thread_id: str | None = None,
        *,
        route_override: str | None = None,
        input_type: str | None = None,
        web_search: bool = False,
        deep_research: bool = False,
    ) -> str:
        forced_category = resolve_forced_category(
            route_override=route_override,
            input_type=input_type,
            web_search=web_search,
            deep_research=deep_research,
        )
        if forced_category:
            logger.info(
                "orchestrator route resolved",
                extra={"component": forced_category, "reason_code": "policy"},
            )
            return forced_category

        # ⚠️ Здесь стоял ВТОРОЙ LLM-роутер по тому же тексту. Он звался только когда
        # авто-оркестратор не участвовал, а это либо явный выбор человека (обработан выше и
        # до модели не доходит), либо СБОЙ решателя — и тогда второй вызов шёл к тому же
        # провайдерскому стеку, который только что не справился. Второго мнения это не
        # давало; давало лишний вызов и задержку до первого токена.
        logger.info(
            "orchestrator route resolved",
            extra={"component": "general", "reason_code": "fallback"},
        )
        return "general"

    def get_agent(self, agent_name: str) -> BaseAgent:
        """Return concrete agent for resolved route."""
        agent = self._agents.get(agent_name)
        if agent is None:
            logger.warning("unknown agent route", extra={"failure_code": "invalid"})
            agent = self._agents.get("general")
        return agent
