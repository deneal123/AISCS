"""Токенный бюджет контекста (Фаза 3).

Эвристическая оценка токенов и покомпонентное распределение бюджета — без жёсткой
зависимости от токенизатора. Используется context_enricher при включённом
``AGENTS__TOKEN_BUDGET_ENABLED`` (иначе работает прежняя обрезка по символам).
"""

from __future__ import annotations

# Среднее число символов на токен. Латиница ≈4, кириллица ≈2.5: BPE-токенизаторы дают на
# кириллицу заметно больше токенов на символ.
#
# ⚠️ КОНСЕРВАТИВНАЯ НИЖНЯЯ ГРАНИЦА 2.5 ОСТАЁТСЯ — но только там, где ошибка в бо́льшую
# сторону опасна. Раньше она применялась ВЕЗДЕ, и на англоязычном тексте это давало
# систематическую потерю: попросив уложить в 1000 токенов, обрезка отдавала 627 —
# 37% выделенного окна не использовалось. Бьёт как раз по коду, логам и JSON, то есть по
# тому, что чаще всего и прикладывают файлом.
_CHARS_PER_TOKEN = 2.5
_CHARS_PER_TOKEN_LATIN = 4.0
_CHARS_PER_TOKEN_CYRILLIC = 2.5


# estimate_tokens живёт в `shared/token_estimate.py`: по нему воркер РЕЗЕРВИРУЕТ кредиты
# до прогона, а движок режет контекст. Две копии формулы означали бы, что резерв и
# реальная работа считаются по-разному — молча и в чью-то пользу. Здесь ре-экспорт для
# прежних вызовов. (Раньше комментарий отсылал к `gpthub_core` — тот пакет ликвидирован.)
from service.shared.token_estimate import estimate_tokens  # noqa: E402


def chars_for_tokens(tokens: int) -> int:
    """Сколько символов гарантированно укладывается в бюджет токенов (нижняя граница).

    ⚠️ Здесь пессимизм УМЕСТЕН: функция отвечает на вопрос «сколько влезет наверняка», и
    ошибка в бо́льшую сторону означала бы переполнение окна модели. Для обрезки
    конкретного текста есть `trim_text_to_tokens`, который смотрит на сам текст.
    """
    return max(0, int(int(tokens or 0) * _CHARS_PER_TOKEN))


def allocate_budget(total_tokens: int, weights: dict[str, float]) -> dict[str, int]:
    """Распределить общий бюджет токенов по компонентам пропорционально весам."""
    total = max(0, int(total_tokens or 0))
    clean = {k: max(0.0, float(v or 0.0)) for k, v in (weights or {}).items()}
    weight_sum = sum(clean.values())
    if total == 0 or weight_sum <= 0:
        return {k: 0 for k in clean}
    return {k: int(total * (w / weight_sum)) for k, w in clean.items()}


def trim_messages_to_tokens(messages: list[dict], budget_tokens: int) -> list[dict]:
    """Оставить самые свежие сообщения, укладывающиеся в бюджет токенов.

    Старейшие сообщения отбрасываются первыми; порядок сохраняется. При нулевом/
    отрицательном бюджете возвращается пустой список.
    """
    if not messages:
        return []
    budget = int(budget_tokens or 0)
    if budget <= 0:
        return []
    kept_reversed: list[dict] = []
    used = 0
    for msg in reversed(messages):
        cost = estimate_tokens(str(msg.get("content", "")))
        if used + cost > budget:
            if kept_reversed:
                break
            # Даже САМОЕ СВЕЖЕЕ сообщение не влезает целиком. Раньше его впускали как
            # есть (kept_reversed пуст → условие не срабатывало) — один огромный тёрн
            # (напр. вставленная простыня) переполнял окно, а safety-net историю не
            # трогал → провайдер отвергал промпт. Обрезаем его по остатку бюджета.
            remaining = budget - used
            truncated = dict(msg)
            truncated["content"] = trim_text_to_tokens(str(msg.get("content", "")), remaining)
            if str(truncated["content"]).strip():
                kept_reversed.append(truncated)
            break
        used += cost
        kept_reversed.append(msg)
    return list(reversed(kept_reversed))


def trim_text_to_tokens(text: str, budget_tokens: int) -> str:
    """Обрезать текст до бюджета токенов.

    ⚠️ Плотность берётся ИЗ САМОГО ТЕКСТА, а не из константы. Раньше здесь стояли
    фиксированные 2.5 симв/токен, тогда как `estimate_tokens` адаптивен (2.5 для
    кириллицы, 4.0 для латиницы) — и эта асимметрия систематически резала англоязычный
    текст на 37% глубже, чем нужно: просим 1000 токенов, получаем 627. Теперь обе
    стороны считают одинаково.

    ⚠️ Общую формулу `estimate_tokens` не трогаем: она закреплена побайтовым вектором с
    копией backend'а (по ней воркер резервирует кредиты), и расхождение означало бы, что
    резерв и реальная работа считаются по-разному. Здесь мы её ИСПОЛЬЗУЕМ, а не меняем.
    """
    budget = int(budget_tokens or 0)
    if budget <= 0:
        return ""
    source = str(text or "")
    estimated = estimate_tokens(source)
    if estimated <= budget:
        return source
    # Плотность ЭТОГО текста: символов на токен по его же оценке.
    density = len(source) / estimated if estimated else _CHARS_PER_TOKEN
    max_chars = max(1, int(budget * density))
    marker = "\n...[обрезано по бюджету]"

    # ⚠️ ПРОВЕРЯЕМ ИТОГОВУЮ СТРОКУ, А НЕ СРЕЗ. Две причины, обе всплыли на замерах:
    # плотность средняя по всему тексту, а оставляем мы НАЧАЛО — у него она может быть
    # другой (смешанный текст давал 125% бюджета); и сама пометка об обрезке — это тоже
    # токены, причём кириллические, то есть дорогие. Проверка среза давала 1002 токена
    # при бюджете 1000 ровно из-за неё.
    #
    # Перебор опаснее недобора: это переполнение окна и 400 от провайдера, а не просто
    # неиспользованное место. Цикл сходится за 1-2 шага и ограничен сверху.
    for _ in range(6):
        candidate = (
            source[:max_chars]
            if max_chars <= len(marker) + 1
            else source[: max_chars - len(marker)] + marker
        )
        if estimate_tokens(candidate) <= budget:
            return candidate
        max_chars = max(1, int(max_chars * 0.9))
    return source[:max_chars]
