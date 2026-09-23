"""Сжатие вывода инструмента: сохранить смысл, а не первые N символов.

🔴 ЧЕМ ПЛОХА ПРОСТАЯ ОБРЕЗКА. Она оставляет НАЧАЛО и выбрасывает КОНЕЦ, а у вывода сборки,
тестов или команды смысл как раз в конце: там код возврата, там сообщение об ошибке, там
итог. Модель получала заголовок компиляции и ни строчки о том, чем всё кончилось, — и
отвечала уверенно, потому что отличить обрезанный вывод от короткого ей нечем.

Пока инструментов было шесть и все возвращали короткие ответы, цена ошибки была невелика.
С приходом `ws_run` в контекст поехали логи сборок и трассировки — то есть ровно тот случай,
против которого обрезка бессильна.

Три приёма, по возрастанию потери:
1. **Дедуп повторов** — потерь нет вовсе: одинаковые строки схлопываются с пометкой «×N».
   Прогресс-бары, повторяющиеся предупреждения и циклы этим убираются целиком.
2. **Голова и хвост** — вместо «первых N символов» берём начало И конец с явным маркером
   пропуска между ними.
3. **Значимые строки из середины** — то, ради чего инструмент и звали: `FAILED`, `ERROR`,
   `npm ERR!`, `fatal:`, `CONFLICT`, итоговая полоса pytest. Это и есть «осведомлённость
   о команде», но СЛОВАРЁМ, а не тремя парсерами: парсер pytest, парсер npm и парсер git
   разошлись бы с апстримом поодиночке и молча, а список слов ошибается разве что в
   сторону «оставили лишнюю строку».

⚠️ Сжатие обязано БЫТЬ ВИДНЫМ. Молча укоротившийся результат неотличим от полного, и
именно это делало обрезку опасной; поэтому каждая потеря отмечается в самом тексте.
"""

from __future__ import annotations

import re

# Доля потолка под хвост. Хвост важнее головы: там итог. Голова нужна, чтобы модель
# понимала, ЧТО выполнялось.
TAIL_SHARE = 0.6
# Дедуп включаем только когда строк достаточно, чтобы повтор был осмысленным.
MIN_LINES_TO_DEDUP = 8
# Счётчик у строки-повтора не должен путаться с содержимым — маркер явный.
_REPEAT = " ⟨повтор ×{count}⟩"
_GAP = "\n… ⟨пропущено {count} симв. середины⟩ …\n"

# Изменчивая часть строки: время, счётчики, проценты, адреса в памяти. Без нормализации
# «одинаковых» строк почти не бывает — каждая отличается миллисекундой.
_VOLATILE = re.compile(
    r"\d{2}:\d{2}:\d{2}(?:[.,]\d+)?|0x[0-9a-fA-F]{4,}|\b\d+(?:[.,]\d+)?%|\b\d{4,}\b"
)


# Сколько потолка отдаём под спасённые из середины значимые строки. Больше — голова с
# хвостом перестанут помещаться; меньше — спасать нечего.
SALVAGE_SHARE = 0.35
_SALVAGE_HEADER = "\n⟨значимые строки из пропущенного⟩\n"

# Словарь значимого в выводе сборок, тестов и git. Проверяется ПОСТРОЧНО. Ложное
# срабатывание стоит одной лишней строки; пропуск — потерянной причины провала.
_SIGNIFICANT = re.compile(
    r"^\s*(FAILED|ERROR|FAIL)\b"  # pytest, go test, ctest
    r"|^\s*(npm\s+ERR!|yarn\s+error)"  # npm / yarn
    r"|^\s*(fatal|error):"  # git, компиляторы
    r"|^\s*CONFLICT\b"  # git merge
    r"|^=+\s.*\s=+$"  # итоговая полоса pytest
    r"|^\s*(Traceback|AssertionError|SyntaxError)\b"
    r"|^\s*\w*Error:"  # ValueError:, TypeError: …
    r"|\b(exit\s+code|exited\s+with)\b"
)


def significant_lines(text: str, budget: int) -> list[str]:
    """Строки, ради которых инструмент и звали. Пусто — ничего значимого не нашлось.

    ⚠️ Берём ПОСЛЕДНИЕ подходящие, а не первые: у длинного прогона ранние ошибки часто
    вторичны (каскад), а решает та, что ближе к итогу. Порядок в выдаче сохраняем
    исходный — перемешанный лог читается хуже обрезанного.
    """
    if budget <= 0:
        return []
    found = [line for line in text.split("\n") if _SIGNIFICANT.search(line)]
    out: list[str] = []
    used = 0
    for line in reversed(found):
        if used + len(line) + 1 > budget:
            break
        out.append(line)
        used += len(line) + 1
    return list(reversed(out))


def _fingerprint(line: str) -> str:
    return _VOLATILE.sub("#", line.strip())


def collapse_repeats(text: str) -> str:
    """Схлопнуть подряд идущие одинаковые строки. Потерь смысла нет.

    ⚠️ Сравниваем по ОТПЕЧАТКУ, а не побайтово: строки лога различаются меткой времени и
    счётчиком, и побайтовое сравнение не схлопнуло бы ничего — то есть приём выглядел бы
    работающим и не работал.
    """
    lines = text.split("\n")
    if len(lines) < MIN_LINES_TO_DEDUP:
        return text
    out: list[str] = []
    previous: str | None = None
    count = 0
    for line in lines:
        current = _fingerprint(line)
        if previous is not None and current == previous:
            count += 1
            continue
        if count:
            out[-1] += _REPEAT.format(count=count + 1)
            count = 0
        out.append(line)
        previous = current
    if count:
        out[-1] += _REPEAT.format(count=count + 1)
    return "\n".join(out)


def head_and_tail(text: str, limit: int) -> str:
    """Сохранить начало И конец. Хвост важнее: там код возврата и сообщение об ошибке.

    ⚠️ Маркер пропуска ВХОДИТ в потолок, а не добавляется сверх него: потолок — это бюджет
    того, что уедет в промпт, и «лимит плюс немного» превращает его в пожелание. Про это
    уже спотыкались: два места считали длину по-разному.
    """
    if len(text) <= limit:
        return text
    marker = _GAP.format(count=len(text))
    budget = max(0, limit - len(marker))
    tail_len = int(budget * TAIL_SHARE)
    head_len = max(0, budget - tail_len)
    dropped = len(text) - head_len - tail_len
    head = text[:head_len]
    tail = text[len(text) - tail_len :] if tail_len else ""
    return head + _GAP.format(count=dropped) + tail


def compact(text: str, limit: int | None) -> tuple[str, bool]:
    """Уложить вывод в потолок с наименьшей потерей. Возвращает текст и признак потери.

    Признак нужен вызывающему: он решает, сообщать ли о сжатии наружу. Молчаливое
    сокращение — ровно та болезнь, ради которой модуль и написан.
    """
    compacted, report = compact_with_report(text, limit)
    return compacted, report["lossy"]


def compact_with_report(text: str, limit: int | None) -> tuple[str, dict]:
    """То же, но с ОТЧЁТОМ: что применилось и сколько осталось.

    ⚠️ Отчёт — не украшение. Незаметно урезанный результат неотличим от неполного ответа
    инструмента, и разбираться в этом пришлось бы по чужим логам. Наружу его выводит
    вызывающий — тем же каналом, которым уже сообщает об отсеянных инструментах.
    """
    raw = str(text or "")
    report: dict = {"lossy": False, "before": len(raw), "after": len(raw), "applied": []}
    if limit is None or len(raw) <= limit:
        return raw, report

    collapsed = collapse_repeats(raw)
    if len(collapsed) < len(raw):
        report["applied"].append("dedup")
    if len(collapsed) <= limit:
        # Повторы схлопнуты — содержимое НЕ потеряно, только его дубликаты.
        report["after"] = len(collapsed)
        return collapsed, report

    # 🔴 ЗНАЧИМОЕ СПАСАЕМ ДО ТОГО, как выбросим середину: после выбрасывания его уже нет.
    salvaged = significant_lines(collapsed, int(limit * SALVAGE_SHARE))
    extra = ""
    budget = limit
    if salvaged:
        extra = _SALVAGE_HEADER + "\n".join(salvaged)
        budget = max(0, limit - len(extra))
        report["applied"].append("salvage")
    result = head_and_tail(collapsed, budget) + extra
    report["applied"].append("head_tail")
    report["lossy"] = True
    report["after"] = len(result)
    return result, report
