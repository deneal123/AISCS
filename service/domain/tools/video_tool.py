"""Инструмент `watch_video`: агент СМОТРИТ ролик по ссылке.

🔴 ИНСТРУМЕНТ, А НЕ СУБАГЕНТ. Он производит данные — кадры и расшифровку — для того
агента, который и так отвечает. Отдельный субагент дублировал бы мультимодальный fan-out,
который у нас уже есть, и завёл бы второй путь к тем же картинкам.

🔴 ДОРОГОЙ И ЗАПЕРТ ПРИЗНАКОМ. Час ролика — это сотня кадров (десятки тысяч токенов
изображений) плюс расшифровка, и всё это переезжает в КАЖДОЕ следующее сообщение треда.
Инструмент зовёт МОДЕЛЬ посреди прогона, спросить в этот момент уже некого — поэтому
`cost_class=expensive` и выдача только по признаку контекста, который ставит оркестратор
после согласия человека. Без признака `ToolSpec` объявить нельзя, это проверяет он сам.

⚠️ КАДРЫ ВОЗВРАЩАЮТСЯ НЕ МОДЕЛИ, А В ОПИСЬ ПРОГОНА. Инструмент отдаёт модели ТЕКСТ —
расшифровку и опись увиденного, — а сами картинки уезжают тем же путём вложений, которым
уже ходят изображения пользователя. Отдать base64 в результат инструмента значило бы
загнать мегабайты в переписку, где они переотправляются каждым следующим раундом.
"""

from __future__ import annotations

import logging

from agents import FunctionTool, RunContextWrapper

from service.domain.capabilities.agent_spec import COST_EXPENSIVE
from service.domain.capabilities.tool_spec import ToolSpec
from service.infrastructure.sidecar import SidecarClient, SidecarError
from service.settings import config
from service.shared.agent_settings import runtime_settings

logger = logging.getLogger(__name__)

CONTEXT_ATTR = "video_tool_enabled"
BILLING_NAME = "watch_video"
# Сколько реплик расшифровки отдаём модели. ⚠️ Потолок нужен именно здесь: расшифровка
# часовой лекции — это тысячи строк, и они поедут в контекст каждого следующего сообщения.
MAX_CUES = 400
MAX_TRANSCRIPT_CHARS = 12_000


def _client() -> SidecarClient | None:
    """Клиент сайдкара или `None`, если способность выключена либо адрес не задан.

    ⚠️ Через админ-снимок и ОДНИМ выражением с дефолтом (`get_agents("x", config…x)`).
    Обёртка-помощник вокруг снимка выглядела короче, но прятала чтение от стража
    полу-управляемых настроек — и он справедливо покраснел: по коду становилось не видно,
    слушает ли настройка админку, а «наполовину слушает» это худший из вариантов.
    """
    if not bool(runtime_settings.get_agents("video_enabled", config.agents.video_enabled)):
        return None
    base = str(runtime_settings.get_agents("video_url", config.agents.video_url) or "")
    timeout = float(
        runtime_settings.get_agents("video_timeout_sec", config.agents.video_timeout_sec) or 480.0
    )
    client = SidecarClient(service="video", base_url=base, timeout=timeout)
    return client if client.available else None


def _context(ctx: RunContextWrapper):
    context = getattr(ctx, "context", None)
    return context


async def watch_video_tool(ctx: RunContextWrapper, arguments: str) -> str:
    """Посмотреть ролик и вернуть модели ТЕКСТ: что было видно и что было сказано."""
    import json

    from service.domain.tools import unbilled_calls

    try:
        args = json.loads(arguments or "{}")
    except ValueError:
        return "Не разобрал аргументы вызова. Передай ссылку на ролик полем url."
    url = str((args or {}).get("url") or "").strip()
    if not url:
        return "Ссылка на ролик не передана — смотреть нечего."

    client = _client()
    if client is None:
        # 🔴 Ролик не посмотрен — надбавка (она покрывает скачивание, ffmpeg и хранение
        # кадров) не заработана. Плата за неоказанную услугу — тот же дефект, что замерен
        # на упавшем веб-поиске.
        unbilled_calls.waive(BILLING_NAME)
        return "Просмотр видео сейчас недоступен. Скажи об этом прямо, не выдумывай содержание."

    context = _context(ctx)
    payload = {
        "url": url,
        # 🔴 ОКНО РЕАЛЬНОЙ МОДЕЛИ ПРОГОНА, а не константа: от него сайдкар считает, сколько
        # кадров вообще уместится рядом с историей, памятью и вложениями.
        "context_tokens": int(getattr(context, "context_budget_tokens", 0) or 32_000),
        "detail": str((args or {}).get("detail") or "balanced"),
    }
    # API key is intentionally environment-only. The admin settings overlay is
    # distributed with every chat run and must never contain a secret.
    key = str(config.agents.video_api_key or "")
    try:
        data = await client.request_json(
            "POST",
            "/watch",
            json_body=payload,
            headers={"Authorization": f"Bearer {key}"} if key else None,
        )
    except SidecarError as exc:
        # ⚠️ Причину НАЗЫВАЕМ модели: «не смог» без причины она перескажет как «видео
        # недоступно», а отказ по длительности и сбой сети требуют разного от человека.
        logger.warning("video sidecar failed code=%s", exc.code)
        unbilled_calls.waive(BILLING_NAME)
        return (
            f"Посмотреть ролик не удалось (код: {exc.code}). "
            "Скажи об этом прямо, не выдумывай содержание."
        )

    frames = data.get("frames") or []
    if context is not None and frames:
        # Картинки уезжают ОПИСЬЮ ПРОГОНА — тем же путём вложений, которым уже ходят
        # изображения пользователя. В результат инструмента они не попадают: там они
        # переотправлялись бы каждым следующим раундом.
        #
        # 🔴 КОНТЕКСТ БЫВАЕТ СЛОВАРЁМ, И НА ЭТОМ ВСЁ ПАДАЛО. Живой прогон с подтверждённым
        # согласием: «Tool 'watch_video' failed: 'dict' object has no attribute
        # 'watched_frames' and no __dict__ for setting new attributes». То есть при
        # УСПЕШНОМ просмотре инструмент падал ровно на записи кадров, и человек получал
        # «не удалось посмотреть ролик» — при живом сайдкаре и скачанных кадрах.
        # Соседний `workspace_tools._ref` читает обе формы по той же причине.
        _remember_frames(context, frames)
    return _describe(data)


def _remember_frames(context, frames: list) -> None:
    """Дописать кадры в опись прогона, чем бы контекст ни оказался."""
    if isinstance(context, dict):
        context["watched_frames"] = list(context.get("watched_frames") or []) + frames
        return
    try:
        context.watched_frames = list(getattr(context, "watched_frames", None) or []) + frames
    except (AttributeError, TypeError):
        # Контекст без слотов под кадры — просмотр состоялся, описание уже собрано;
        # ронять из-за этого весь инструмент нельзя.
        logger.warning("кадры некуда записать: контекст %s не принимает их", type(context).__name__)


def _duration_words(seconds: float) -> str:
    """Длительность словами. ⚠️ Минутами всегда — это «длительность 0 мин.» на коротком
    ролике: модель перескажет это человеку буквально, и ответ прочитается как поломка.
    Замерено живьём на десятисекундном клипе."""
    total = int(round(max(0.0, float(seconds))))
    if total < 60:
        return f"{total} с"
    if total < 3600:
        return f"{total // 60} мин {total % 60:02d} с" if total % 60 else f"{total // 60} мин"
    hours, rest = divmod(total, 3600)
    return f"{hours} ч {rest // 60:02d} мин"


def _describe(data: dict) -> str:
    """Текст для модели: что за ролик, сколько увидено и что сказано."""
    title = str(data.get("title") or "").strip()
    duration = float(data.get("duration_sec") or 0.0)
    frames = data.get("frames") or []
    cues = (data.get("transcript") or [])[:MAX_CUES]

    head = [
        f"Просмотрен ролик{f' «{title}»' if title else ''}"
        + (f", длительность {_duration_words(duration)}." if duration else "."),
        f"Кадров показано: {len(frames)} из {data.get('frames_examined') or len(frames)} "
        "просмотренных — они приложены к этому сообщению как изображения.",
    ]
    # 🔴 «ПОСМОТРЕЛ РОЛИК» И «ПОСМОТРЕЛ СТО КАДРОВ ИЗ ЧАСА» — РАЗНЫЕ УТВЕРЖДЕНИЯ, и второе
    # модель обязана уметь произнести. Без этой строки она отвечает так, будто видела всё.
    if data.get("truncated"):
        head.append(
            "⚠️ Показаны НЕ ВСЕ кадры: между ними есть пропуски. Не утверждай, что видел "
            "ролик целиком, и не описывай происходящее в промежутках."
        )
    for warning in data.get("warnings") or []:
        head.append(f"⚠️ {warning}")

    if cues:
        text = "\n".join(f"[{c.get('t_sec', 0):.0f}с] {c.get('text', '')}" for c in cues)
        head.append("Расшифровка:\n" + text[:MAX_TRANSCRIPT_CHARS])
    else:
        head.append("Расшифровки нет — опирайся на кадры и не выдумывай реплики.")
    return "\n".join(head)


watch_video = FunctionTool(
    name="watch_video",
    description=(
        "Посмотреть видео по ссылке: вернуть кадры и расшифровку. Вызывай, когда человек "
        "прислал ссылку на ролик и просит пересказать, найти момент, разобрать или "
        "прокомментировать увиденное. Дорогая операция: один вызов на один ролик."
    ),
    params_json_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Прямая ссылка на видео."},
            "detail": {
                "type": "string",
                "enum": ["quick", "balanced", "deep"],
                "description": (
                    "Подробность просмотра. quick — общее представление, deep — разбор по "
                    "моментам. По умолчанию balanced."
                ),
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    on_invoke_tool=watch_video_tool,
)


SPECS = [
    ToolSpec(
        name="watch_video",
        tool=watch_video,
        requires_context_attr=CONTEXT_ATTR,
        billing_name=BILLING_NAME,
        cost_class=COST_EXPENSIVE,
        confirm_by_default=True,
        selector_hint="проанализировать видео по ссылке или из доступного контекста",
        # Результат — текст описания и расшифровка; резать его общим потолком нельзя:
        # обрезанная посередине расшифровка выглядит как оборванная мысль спикера.
        result_limit_chars=None,
        # Дедлайн БОЛЬШЕ серверного у сайдкара — иначе мы уходим раньше, чем он успевает
        # ответить отказом, и причина отказа теряется.
        default_timeout_sec=480.0,
    )
]
