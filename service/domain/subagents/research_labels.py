"""Оформление вех хода исследования: чистка эмодзи + русификация меток LDR.

Вынесено из сабагента как самостоятельный узел: это чистое представление, и держать
его рядом с оркестрацией прогонов незачем — файл сабагента перерос лимит сложности.

⚠️ Правило оформления одно на оба пути. LDR присылает вехи со своими эмодзи (🔍/📄/…),
и они здесь ВЫРЕЗАЮТСЯ: иконки рисует трейс-панель, а не текст. Нативный путь тем
временем печатал точно такие же эмодзи сам, да ещё и в тело отчёта — из-за чего два
режима одного продукта выглядели по-разному. Теперь оба отдают чистые метки событиями.
"""

from __future__ import annotations

import re

# LDR вставляет эмодзи (🔍/📄/…) в свои milestone-сообщения — вырезаем, чтобы
# трейс был строго под наш дизайн (оформление — иконками панели, не эмодзи).
_EMOJI_RE = re.compile("[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff←-⇿⬀-⯿️]")


def clean_label(text: str) -> str:
    return _EMOJI_RE.sub("", text or "").strip()


# Русификация статус-вех LDR (приходят на английском). Точечный маппинг фраз с
# сохранением динамики (числа) и имён движков (SearXNG/arXiv/… — как есть).
_PHASE_RU = {
    "init": "Инициализация",
    "planning": "Планирование",
    "searching": "Поиск источников",
    "synthesis": "Синтез ответа",
    "final_filtering": "Финальная фильтрация",
    "complete": "Исследование завершено",
    "analyzing": "Анализ источников",
}
_L10N = (
    (
        re.compile(r"planning approach with (\d+) research tools? available"),
        r"планирую подход, доступно инструментов: \1",
    ),
    (re.compile(r"(\d+) sources? gathered"), r"собрано источников: \1"),
    (re.compile(r"selecting next action from "), "выбираю следующий шаг из: "),
    (
        re.compile(r"Synthesizing (\d+) sources? with citations"),
        r"синтезирую ответ (источников: \1)",
    ),
    (
        re.compile(r"Refinement search found (\d+) sources?"),
        r"уточняющий поиск: найдено источников \1",
    ),
    (
        re.compile(r"After refinement: (\d+) total sources?"),
        r"после уточнения всего источников: \1",
    ),
    (re.compile(r"\bResearch complete\b"), "исследование завершено"),
    (re.compile(r"\+(\d+) more"), r"+ещё \1"),
    (re.compile(r"\band (\d+) more\b"), r"и ещё \1"),
    (re.compile(r"\bStep\b"), "Шаг"),
    (re.compile(r"\bthe web\b"), "веб"),
    (re.compile(r"\bFetch Content\b"), "загрузка страниц"),
)


def localize_label(text: str) -> str:
    if not text:
        return text
    phase = _PHASE_RU.get(text.strip().lower())
    if phase:
        return phase
    out = text
    for rx, rep in _L10N:
        out = rx.sub(rep, out)
    return out


def status_info(status: dict) -> tuple[int | None, str]:
    """(progress:int|None, label:str) из ответа статуса LDR. Без эмодзи —
    оформление берёт на себя трейс-панель. Текст-веха берётся из log_entry/
    message/phase, если LDR их прислал (обычный поллинг даёт только progress)."""
    if not isinstance(status, dict):
        return None, ""
    raw = status.get("progress") or status.get("percentage") or status.get("percent")
    try:
        progress = int(float(raw)) if raw not in (None, "") else None
    except (TypeError, ValueError):
        progress = None
    log = status.get("log_entry") if isinstance(status.get("log_entry"), dict) else {}
    label = (
        status.get("message")
        or status.get("status_message")
        or (log.get("message") if isinstance(log, dict) else None)
        or status.get("phase")
        or status.get("stage")
        or status.get("current_task")
        or ""
    )
    return progress, localize_label(clean_label(str(label)))
