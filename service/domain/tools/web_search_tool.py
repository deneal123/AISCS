"""Веб-поиск как ИНСТРУМЕНТ обычного ответа — рядом с маршрутом, а не вместо него.

Маршрут отвечает на прямую просьбу «найди». Инструмент нужен для другого, более частого
случая: человек просит написать или объяснить, а ответ упирается в устаревающий факт.
Маршрут там забирает запрос себе и отдаёт подборку источников вместо письма.

🔴 Выдаётся НЕ ВСЕГДА: схема стоит токенов в каждом запросе, включая «привет». Гейт тот
же структурный, что у `analyze_data`, — по решению оркестратора о свежих данных.

⚠️ Возвращаем заголовки и выдержки, не тела страниц: результат переотправляется каждым
раундом tool-loop, и однажды это уже раздуло промпт до 89k. Для текста целиком есть
`fetch_url`.
"""

from __future__ import annotations

import json
import logging

from agents import FunctionTool, RunContextWrapper

from service.domain.capabilities.tool_spec import GROUNDING_FRESH_DATA, ToolSpec

logger = logging.getLogger(__name__)

_MAX_RESULTS = 5
_MAX_SNIPPET = 300

# 🔴 Имя для тарификации, отдельное от маршрутного: цена ищется через `.get`, промахов он
# не сообщает — совпадение имён молча дало бы цену маршрута.
BILLING_NAME = "web_search_tool"


async def search_web_tool(ctx: RunContextWrapper, args: str) -> str:
    """Найти в интернете свежие факты по запросу."""
    from service.domain.tools import unbilled_calls
    from service.domain.tools.web_search import web_search

    try:
        parsed = json.loads(args) if isinstance(args, str) else (args or {})
        query = str((parsed or {}).get("query") or "").strip()
    except Exception:  # noqa: BLE001 — аргументы пишет модель, кривой JSON тут норма
        query = str(args or "").strip()
    if not query:
        return "Пустой запрос — уточни, что именно искать."

    engines: dict = {}
    try:
        results = await web_search(query, num_results=_MAX_RESULTS, stats=engines)
    except Exception:
        logger.warning("search_web failed code=internal")
        # 🔴 УСЛУГИ НЕ БЫЛО — НАДБАВКИ НЕТ. Замерено: движки отвалились по таймауту, а с
        # человека всё равно взяли 833 кредита сверх токенов за «веб-поиск».
        unbilled_calls.waive(BILLING_NAME)
        return (
            "Поиск сейчас недоступен. Ответь по имеющимся знаниям и прямо скажи, "
            "что свежих данных получить не удалось."
        )

    if not results:
        # 🔴 ДВА РАЗНЫХ ПУСТЫХ ОТВЕТА. «Движки ответили, находок нет» — законный результат
        # поиска, он платный. «Не ответил ни один» (замеренный случай: таймаут на всех) —
        # услуги не было, надбавку не берём и говорим модели другое: искать нечего не
        # потому, что в сети пусто, а потому, что поиск не состоялся.
        if not engines.get("engines_answered"):
            unbilled_calls.waive(BILLING_NAME)
            return (
                "Поиск сейчас недоступен: ни один движок не ответил. Ответь по имеющимся "
                "знаниям и прямо скажи, что свежих данных получить не удалось."
            )
        return f"По запросу «{query}» ничего не найдено. Скажи об этом прямо, не выдумывай данные."

    # 🔴 Найденное запоминается ПРОГОНУ, а не только этому раунду: иначе ссылки живут
    # ровно до конца хода, и следующий вопрос «а что там по этой вакансии» получает
    # «я не вижу описания, пришлите ссылку» — про источник, который агент сам же нашёл.
    from service.domain.tools import found_sources

    found_sources.remember(results[:_MAX_RESULTS])

    lines = [f"Результаты поиска по «{query}» (заголовок · источник · выдержка):"]
    for item in results[:_MAX_RESULTS]:
        title = str((item or {}).get("title") or "").strip()
        url = str((item or {}).get("url") or "").strip()
        snippet = str((item or {}).get("snippet") or "").strip()[:_MAX_SNIPPET]
        lines.append(f"- {title} · {url}\n  {snippet}")
    lines.append("Опирайся на эти источники и ССЫЛАЙСЯ на них в ответе.")
    return "\n".join(lines)


search_web = FunctionTool(
    name="search_web",
    description=(
        "Найти в интернете АКТУАЛЬНЫЕ факты, когда ответ зависит от данных, которые могли "
        "измениться: цены, курсы, версии, события, состав и статус организаций. Возвращает "
        "заголовки, ссылки и выдержки. Для полного текста конкретной страницы используй "
        "fetch_url. Не вызывай для устойчивого знания (математика, история, устройство "
        "алгоритмов) — там поиск ничего не добавит."
    ),
    params_json_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Поисковый запрос. Формулируй как в поисковике, без лишних слов.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    on_invoke_tool=search_web_tool,
)


# ⚠️ Выдаётся ТОЛЬКО когда оркестратор сказал «нужны свежие данные»: схема стоит токенов в
# каждом запросе, а без такого решения инструмент бесполезен. Имя надбавки ОТДЕЛЬНОЕ от
# маршрутного `web_search` — совпадение дало бы цену маршрута там, где субагент с синтезом
# не запускался.
SPECS = [
    ToolSpec(
        name="search_web",
        tool=search_web,
        requires_context_attr="web_tool_enabled",
        billing_name=BILLING_NAME,
        selector_hint="найти актуальные внешние факты, цены, версии или события",
        dedup_safe=True,
        grounding_roles=frozenset({GROUNDING_FRESH_DATA}),
    )
]
