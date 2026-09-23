"""Reusable Agent SDK tools for GPTHub assistants."""

from __future__ import annotations

import json
import logging

from agents import FunctionTool, RunContextWrapper

logger = logging.getLogger(__name__)

_TOOL_CONTEXT_FIELDS = frozenset({"user_id", "repo_graph_ids", "tabular_files"})


def _context_dict(ctx: RunContextWrapper) -> dict:
    context = getattr(ctx, "context", None)
    if context is None:
        return {}
    if isinstance(context, dict):
        return {key: context.get(key) for key in _TOOL_CONTEXT_FIELDS if key in context}
    try:
        if hasattr(context, "model_dump"):
            raw = context.model_dump()
            return {key: raw.get(key) for key in _TOOL_CONTEXT_FIELDS if key in raw}
        if hasattr(context, "dict"):
            raw = context.dict()
            return {key: raw.get(key) for key in _TOOL_CONTEXT_FIELDS if key in raw}
    except Exception:
        logger.debug("tool context metric unavailable", extra={"failure_code": "internal"})
    return {}


async def search_knowledge_graph_tool(ctx: RunContextWrapper, args: str) -> str:
    """Обойти граф знаний пользователя (его документы и разобранные репозитории).

    Отвечает на РЕЛЯЦИОННЫЕ вопросы («как X связан с Y», «что завязано на Z») по
    ВСЕМУ корпусу — в отличие от контекста треда, где живёт только последний файл.
    Пусто (нет графа / сайдкар выключен) → так и говорим модели: пусть отвечает
    из того, что есть, а не выдумывает.
    """
    import asyncio

    from service.domain.tools import vector_store
    from service.domain.tools.graphify_client import (
        GraphifyClient,
        user_graph_id,
    )

    try:
        parsed = json.loads(args) if isinstance(args, str) else (args or {})
        question = str((parsed or {}).get("question") or "").strip()
    except Exception:
        question = str(args or "").strip()
    if not question:
        return "Не указан вопрос для поиска по базе знаний."

    ctx_data = _context_dict(ctx)
    user_id = str(ctx_data.get("user_id") or "")
    graph_id = user_graph_id(user_id)
    if not graph_id:
        return "База знаний недоступна: не удалось определить пользователя."

    # ⚠️ КОД РЕПОЗИТОРИЯ ЛЕЖИТ В ОТДЕЛЬНОМ ГРАФЕ. Разобранный на аплоаде репозиторий
    # строится в граф `repo-{uuid}`, а НЕ в личный граф документов юзера. Без запроса к
    # нему инструмент искал код в графе PDF и не находил (живой инцидент: 9 бесплодных
    # вызовов, 9880 кр). Спрашиваем и личный граф (документы), и графы репо этого треда.
    repo_ids = [g for g in (ctx_data.get("repo_graph_ids") or []) if g]
    graph_ids = [graph_id, *repo_ids]

    # ⚠️ return_exceptions: с вариантом B графов стало НЕСКОЛЬКО (личный + repo-графы
    # треда), и любой из repo-графов может протухнуть — Redis ещё держит `graph_id`, а сам
    # граф в graphify уже удалён (TTL рассинхрон) → `query` кидает. Без изоляции один
    # битый граф ронял бы ВЕСЬ поиск, и агент оставался без базы знаний из-за одного
    # мёртвого репо. Упавший источник просто пропускаем.
    client = GraphifyClient()
    results = await asyncio.gather(
        vector_store.search(user_id=user_id, query=question),
        *[client.query(question, graph_id=gid) for gid in graph_ids],
        return_exceptions=True,
    )

    def _ok(v):
        if isinstance(v, Exception):
            logger.debug("knowledge source unavailable", extra={"failure_code": "unavailable"})
            return None
        return v

    passages = _ok(results[0]) or []
    relations_by_graph = [(gid, _ok(r)) for gid, r in zip(graph_ids, results[1:], strict=True)]

    sections: list[str] = []
    if passages:
        quoted = "\n\n".join(
            f"[{hit['filename']}]\n{hit['text']}" for hit in passages if hit.get("text")
        )
        if quoted:
            sections.append(f"## Фрагменты документов (дословно)\n{quoted}")
    for gid, relations in relations_by_graph:
        if relations:
            label = "репозитория" if gid in repo_ids else "знаний"
            sections.append(f"## Связи из графа {label}\n{relations}")

    if not sections:
        return (
            "В базе знаний ничего не найдено (возможно, документы ещё не "
            "проиндексированы). Отвечай по имеющемуся контексту."
        )
    return "\n\n".join(sections)


search_knowledge_graph = FunctionTool(
    name="search_knowledge_graph",
    description=(
        "Искать в базе знаний пользователя — его загруженных документах и разобранных "
        "репозиториях. Возвращает и дословные фрагменты (по смыслу запроса), и связи между "
        "сущностями из графа. Использовать, когда ответа нет в текущем диалоге: например "
        "«что в моих документах про сроки оплаты» или «как связаны X и Y»."
    ),
    params_json_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Вопрос на естественном языке к документам пользователя.",
            }
        },
        "required": ["question"],
    },
    on_invoke_tool=search_knowledge_graph_tool,
)


async def fetch_url_tool(ctx: RunContextWrapper, args: str) -> str:
    """Скачать и извлечь текст ОДНОЙ веб-страницы по прямой ссылке.

    Переиспользует SSRF-защищённый parse_url (валидация схемы/хоста до каждого хопа,
    блок внутренних адресов). Для «прочитай/суммируй вот эту ссылку» — без запуска
    полноценного веб-поиска. Ошибку/пустой текст возвращаем модели словами, а не
    роняем ход.
    """
    from service.domain.tools.web_search import parse_url

    try:
        parsed = json.loads(args) if isinstance(args, str) else (args or {})
        url = str((parsed or {}).get("url") or "").strip()
    except Exception:
        url = str(args or "").strip()
    if not url:
        return "Не указан URL для загрузки."

    result = await parse_url(url, max_chars=5000)
    if result.get("error"):
        return f"Не удалось загрузить страницу ({url}): {result['error']}"
    content = str(result.get("content") or "").strip()
    if not content:
        return (
            f"Страница загружена ({url}), но извлечь основной текст не удалось "
            "(возможно, тяжёлая JS-страница или anti-bot)."
        )
    title = str(result.get("title") or "").strip()
    header = f"# {title}\n{url}\n\n" if title else f"{url}\n\n"
    return header + content


fetch_url = FunctionTool(
    name="fetch_url",
    description=(
        "Скачать и извлечь текст ОДНОЙ веб-страницы по прямой ссылке (http/https). "
        "Использовать, когда пользователь дал конкретный URL и просит его "
        "прочитать/суммировать/проверить — без полноценного веб-поиска. Возвращает "
        "заголовок и основной текст (или сообщение об ошибке). Защита от обращения к "
        "внутренним адресам (SSRF) встроена."
    ),
    params_json_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Прямая ссылка вида http(s)://… на страницу для чтения.",
            }
        },
        "required": ["url"],
    },
    on_invoke_tool=fetch_url_tool,
)


def _md_table(columns: list, rows: list, max_cols: int = 20, max_cell: int = 60) -> str:
    """Список колонок + строк → markdown-таблица (с обрезкой ширины/ячеек)."""
    cols = [str(c) for c in (columns or [])][:max_cols]
    if not cols:
        return "(пустой результат)"

    def cell(v):
        s = "" if v is None else str(v)
        s = s.replace("|", "\\|").replace("\n", " ")
        return s[:max_cell] + "…" if len(s) > max_cell else s

    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    body = ["| " + " | ".join(cell(v) for v in row[:max_cols]) + " |" for row in (rows or [])]
    return (
        "\n".join([head, sep, *body])
        if body
        else "\n".join([head, sep, "| " + " | ".join([""] * len(cols)) + " |"])
    )


def _format_analyze_result(res: dict, sql: str) -> str:
    if res.get("error") == "sql_error":
        detail = str(res.get("detail") or "")
        # 🔴 ОТКАЗ ОБЯЗАН УЧИТЬ, А НЕ ТОЛЬКО СООБЩАТЬ. «file system operations are disabled»
        # ничего не говорит о том, ЧТО делать: замер показал, что модель пересказывала эту
        # фразу человеку как «проблема с настройками файловой системы» — вместо ответа по
        # данным, которые лежали рядом. Подсказка даёт следующий шаг, а не диагноз.
        if "file system operations are disabled" in detail or "Cannot access file" in detail:
            return (
                f"Ошибка SQL: {detail}\n"
                "Причина одна: ты обратился к ФАЙЛУ. Файлов здесь нет — данные уже загружены "
                "как таблицы. Убери `read_csv_auto(...)` / `FROM 'файл.csv'` и обращайся к "
                "таблице по имени из схемы (вызови analyze_data без sql, если имя забыл)."
            )
        return f"Ошибка SQL: {detail}\nИсправь запрос (диалект DuckDB) и вызови analyze_data снова."
    if res.get("error"):
        return f"Не удалось выполнить запрос по данным: {res.get('detail') or res.get('error')}"

    tables = res.get("tables") or []
    if not (sql or "").strip():
        # Разведочный вызов: отдаём модели схему + превью, чтобы она написала SQL.
        lines = ["Загруженные таблицы (из файлов пользователя):"]
        for t in tables:
            cols = ", ".join(f"{c['name']} {c['type']}" for c in (t.get("columns") or []))
            lines.append(f"\n### {t['name']} — из «{t.get('source')}», строк: {t.get('row_count')}")
            lines.append(f"Колонки: {cols}")
            preview = t.get("preview") or []
            if preview:
                lines.append(_md_table([c["name"] for c in t.get("columns") or []], preview))
        # 🔴 «ФАЙЛОВ НЕТ» СКАЗАНО ПРЯМО, и это не педантизм. Замер: модель писала
        # `FROM read_csv_auto('iris.csv')` и `FROM 'iris.csv'`, получала «file system
        # operations are disabled by configuration» и пересказывала это человеку как
        # «проблема связана с настройками файловой системы». Лишний раунд на каждый такой
        # вопрос, а иногда и ответ-отговорка вместо данных. Имя таблицы совпадает с именем
        # файла (так их и различают), поэтому соблазн обратиться к файлу особенно велик.
        first = tables[0]["name"] if tables else "t"
        lines.append(
            f"\nТаблицы УЖЕ ЗАГРУЖЕНЫ в память — обращайся к ним по ИМЕНИ: `FROM {first}`. "
            "Файлов на диске НЕТ: `read_csv_auto('…')`, `FROM 'файл.csv'` и любые файловые "
            "функции DuckDB отключены и вернут ошибку доступа.\n"
            "Напиши SQL (диалект DuckDB) и вызови analyze_data ещё раз."
        )
        return "\n".join(lines)

    columns = res.get("columns") or []
    rows = res.get("rows") or []
    note = (
        f"\n(показаны первые {len(rows)} строк — результат обрезан)" if res.get("truncated") else ""
    )
    return f"Результат SQL ({res.get('row_count', len(rows))} строк){note}:\n{_md_table(columns, rows)}"


async def analyze_data_tool(ctx: RunContextWrapper, args: str) -> str:
    """Выполнить SQL (DuckDB) по табличным файлам пользователя (csv/xlsx/parquet/json).

    Двухшаговый сценарий для модели: сначала вызвать БЕЗ sql — получить схему и превью
    таблиц; затем с готовым SQL. Таблицы названы по файлам. Нет файлов / сайдкар
    выключен — говорим словами, а не выдумываем цифры.
    """
    from service.domain.tools.duckdb_client import (
        DuckDBClient,
        fetch_tabular_files_from_urls,
    )

    try:
        parsed = json.loads(args) if isinstance(args, str) else (args or {})
        sql = str((parsed or {}).get("sql") or "").strip()
    except Exception:
        sql = str(args or "").strip()

    client = DuckDBClient()
    if not client.enabled:
        return "Аналитика по файлам сейчас недоступна (сервис выключен). Ответь по имеющемуся контексту."

    ctx_data = _context_dict(ctx)
    # Файлы приезжают ПРЕЗАЙНЕД-ССЫЛКАМИ в теле /run (Фаза 0b.4): их собирает backend,
    # у которого есть PG и MinIO. Ветки «сходить в хранилище самому» здесь больше нет —
    # она импортировала service.services.chat/service.models, которых в сайдкаре не
    # существует, и вместо вежливого ответа ниже давала ModuleNotFoundError.
    passed_files = ctx_data.get("tabular_files")
    files, skipped = await fetch_tabular_files_from_urls(passed_files) if passed_files else ([], [])
    if not files:
        return (
            "Нет табличных файлов для анализа (csv/xlsx/parquet/json не прикреплены "
            "или недоступны). Попроси пользователя прикрепить таблицу."
        )
    # ⚠️ Пропущенные файлы — В ОТВЕТ МОДЕЛИ. Иначе она делает SQL по подмножеству таблиц
    # и уверенно отвечает по неполным данным; здесь она узнаёт, что часть данных не вошла,
    # и обязана предупредить пользователя.
    skip_note = ""
    if skipped:
        skip_note = (
            "\n\n⚠️ НЕ ПРОАНАЛИЗИРОВАНЫ (данные НЕПОЛНЫЕ, предупреди пользователя): "
            + "; ".join(skipped)
        )

    from service.infrastructure.sidecar import SidecarBadRequest, SidecarError

    try:
        res = await client.query(sql=sql, files=files, max_rows=200)
    except SidecarBadRequest as exc:
        # ⚠️ Отделено от общего отказа НАМЕРЕННО. 4xx означает, что виноват вызывающий:
        # прислали неподдержанный формат, превысили лимит. Это модель может исправить
        # сама — но только если ей сказать, ЧТО не так. Раньше всё сводилось к одному
        # «сервис недоступен», и она просто сдавалась там, где хватило бы другого файла.
        logger.info("analyze_data: запрос отвергнут сайдкаром (%s)", exc.code)
        return (
            f"Сервис аналитики отклонил запрос (код: {exc.code}). "
            "Если дело в формате файла — скажи это пользователю; если в объёме — "
            "предложи сузить выборку."
        )
    except SidecarError as exc:
        logger.warning("analyze_data sidecar failed code=%s", exc.code)
        return (
            "Не удалось обратиться к сервису аналитики по данным. Ответь по имеющемуся контексту."
        )
    except Exception:
        logger.warning("analyze_data sidecar failed code=internal")
        return (
            "Не удалось обратиться к сервису аналитики по данным. Ответь по имеющемуся контексту."
        )
    return _format_analyze_result(res, sql) + skip_note


analyze_data = FunctionTool(
    name="analyze_data",
    description=(
        "Выполнить SQL-запрос (диалект DuckDB) по ТАБЛИЧНЫМ файлам, которые пользователь "
        "прикрепил к диалогу (CSV/Excel/Parquet/JSON) — для точных агрегатов, фильтров, "
        "группировок, трендов по РЕАЛЬНЫМ данным, а не по их текстовому превью. "
        "Сначала вызови БЕЗ параметра sql — получишь схему и первые строки таблиц; затем "
        "вызови с готовым SQL. Таблицы названы по именам файлов."
    ),
    params_json_schema={
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": (
                    "SQL-запрос в диалекте DuckDB по таблицам пользователя. Оставь пустым "
                    "для первого (разведочного) вызова — вернётся схема и превью."
                ),
            }
        },
        "required": [],
    },
    on_invoke_tool=analyze_data_tool,
)

from service.domain.capabilities.tool_spec import (  # noqa: E402
    GROUNDING_FRESH_DATA,
    GROUNDING_REPOSITORY,
    GROUNDING_TABULAR,
    ToolSpec,
)
from service.domain.tools.web_search_tool import search_web  # noqa: E402

# 🔴 Декларации живут РЯДОМ с самими инструментами: новый инструмент — это один модуль
# (или один блок здесь) плюс строка в источниках реестра. Гейт применимости, потолок
# результата и имя надбавки берутся отсюда, а не из трёх разных словарей по коду.
SPECS = [
    ToolSpec(
        name="search_knowledge_graph",
        tool=search_knowledge_graph,
        requires_context_attr="repo_graph_ids",
        selector_hint="найти факты и связи в загруженной базе знаний или карте репозитория",
        dedup_safe=True,
        grounding_roles=frozenset({GROUNDING_REPOSITORY}),
    ),
    ToolSpec(
        name="fetch_url",
        tool=fetch_url,
        selector_hint="загрузить и разобрать конкретную веб-страницу",
        dedup_safe=True,
        grounding_roles=frozenset({GROUNDING_FRESH_DATA}),
    ),
    ToolSpec(
        name="analyze_data",
        tool=analyze_data,
        requires_context_attr="tabular_files",
        selector_hint="выполнить точный SQL-анализ приложенных таблиц",
        dedup_safe=True,
        grounding_roles=frozenset({GROUNDING_TABULAR}),
    ),
]

from service.domain.tools.video_tool import watch_video  # noqa: E402
from service.domain.tools.workspace_tools import WORKSPACE_TOOLS  # noqa: E402

DEFAULT_FUNCTION_TOOLS = [
    # 🔴 `fetch_runtime_context` УДАЛЁН, а не «оставлен на всякий случай». Он отдавал модели
    # четыре служебных поля (timestamp, user_id, thread_id, input_type), применить которые
    # ей нечем, а назывался «получить системный контекст текущего запроса» — то есть ровно
    # тем, что модель ищет, когда её спрашивают про приложенные файлы. Живой прогон
    # («покажи код функции и объясни построчно», архив развёрнут в песочнице): модель
    # вызвала его ПЯТЬ РАЗ подряд, получая по 119 символов, исчерпала `max_turns=4` и
    # вернула «не удалось довести задачу до ответа за отведённое число шагов». Пять вызовов
    # LLM с полным промптом и НУЛЕВОЙ результат для человека.
    #
    # СНАЧАЛА ЛОКАЛЬНЫЕ ИСТОЧНИКИ, ПОТОМ СЕТЬ. Файл в песочнице — точный ответ, страница из
    # интернета — догадка о том же коде.
    #
    # ⚠️ ПОРЯДОК ВЛИЯЕТ СЛАБО, и это проверено: я поменял его, предположив, что модель берёт
    # первый выданный инструмент, — поведение не изменилось ни на один вызов. Настоящей
    # причиной было другое: `ws_*` в том прогоне ВООБЩЕ НЕ ВЫДАВАЛИСЬ (решатель ответил
    # `files_tool: false`), и модель честно искала код в сети, потому что других способов у
    # неё не было. Порядок оставлен как более осмысленный, но чинил не он.
    #
    # ⚠️ Файловые выдаются НЕ ВСЕГДА: без выданной песочницы девять инструментов отсеиваются
    # гейтом `requires_context_attr`, и обычный чат идёт как прежде.
    *WORKSPACE_TOOLS,
    search_knowledge_graph,
    analyze_data,
    fetch_url,
    # ⚠️ Объявлен здесь, но выдаётся НЕ ВСЕГДА: структурный гейт пускает его только когда
    # оркестратор сказал «нужны свежие данные». Схема стоит токенов в каждом запросе, а
    # без свежих данных инструмент бесполезен.
    search_web,
    # 🔴 Просмотр ролика — ДОРОГОЙ, и признак ему ставит не оркестратор сам, а согласие
    # человека: час видео переезжает в контекст каждого следующего сообщения треда.
    watch_video,
]
