"""Табличный ли файл — по ФОРМЕ СОДЕРЖИМОГО, а не по расширению.

🔴 Живой кадр: `А - рассылка.json` + «вычитай 10 строку» → трейс «Табличный файл —
анализирую через SQL», два вызова `analyze_data`, ответ «десятой строки в загруженных
данных нет». Расширение `.json` стояло в списке табличных, и это ПЕРЕКРЫВАЛО выбор
оркестратора детерминированно: задача ЧТЕНИЯ ФАЙЛА уходила в SQL.

`.json` — это две разные вещи, и решает форма, а не имя:
* **таблица** — массив объектов на верхнем уровне, JSONL, обёртка с единственным таким
  массивом внутри (`{"data": [ … ]}`);
* **словарь** — дерево настроек, разнородные вложенные объекты. Такой файл читается
  ТЕКСТОМ и файловыми инструментами.

⚠️ Судим по ГОЛОВЕ файла (десятки килобайт): классификация не должна стоить дороже
самой задачи. Обрыв на середине массива — не ошибка, а норма: сколько элементов успели
прочитать, по стольким и судим.

⚠️ Не распарсилось или неоднозначно → СЛОВАРЬ. Ошибка в эту сторону даёт «прочитал
текстом» (медленнее, но верно), в обратную — «десятой строки нет» на файле, где она есть.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Сколько байт файла достаточно для вердикта.
HEAD_BYTES = 64 * 1024

# Форматы, где ТАБЛИЦА — это сам контейнер: смотреть внутрь незачем, там нет второго
# прочтения. Бинарные, головой их всё равно не разобрать.
FORMAT_IS_TABLE = frozenset({".parquet", ".pqt", ".xlsx", ".xls", ".ods", ".xlsm", ".fods"})

# Расширения, которые САМИ объявляют разделённые данные. Форму мы всё равно смотрим (у
# `.csv` из одной строки нет ни одной записи), но если содержимое недоступно — верим
# объявлению: потерять настоящую таблицу из-за недоступного хранилища хуже, чем прочитать
# её текстом. Двусмысленности, ради которой писан модуль, у этих имён нет.
NAME_DECLARES_TABLE = frozenset({".csv", ".tsv"})

# Форматы, где одно и то же расширение носит и таблицу, и не-таблицу.
SHAPE_DECIDES = frozenset({".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".txt"})

_MAX_PROBE_ITEMS = 24
_MAX_PROBE_LINES = 12
_DELIMITERS = (",", ";", "\t", "|")

_DECODER = json.JSONDecoder()


def _ext(name: str) -> str:
    return Path(str(name or "")).suffix.lower()


def _skip_ws(text: str, idx: int) -> int:
    n = len(text)
    while idx < n and text[idx] in " \t\r\n":
        idx += 1
    return idx


def _uniform_objects(items: list[dict]) -> bool:
    """«В основном совпадающий набор ключей»: общая часть покрывает хотя бы половину.

    Массив разнородных объектов (`[{"a":1},{"b":2}]`) общей части не имеет вовсе — это
    коллекция сущностей, а не таблица, и в SQL ей делать нечего.
    """
    if not items:
        return False
    keysets = [frozenset(it.keys()) for it in items]
    union: set[str] = set().union(*keysets)
    if not union:
        return False
    common = set(keysets[0]).intersection(*keysets)
    return len(common) >= max(1, (len(union) + 1) // 2)


def _scan_array_objects(text: str, idx: int) -> tuple[list[dict], bool]:
    """Элементы массива, начиная сразу после «[». → (что прочли, все ли объекты).

    Обрыв головы посреди элемента останавливает чтение без ошибки: вердикт выносится по
    прочитанному, иначе большой валидный массив классифицировался бы как «не разобрался».
    """
    items: list[dict] = []
    n = len(text)
    while len(items) < _MAX_PROBE_ITEMS:
        idx = _skip_ws(text, idx)
        if idx >= n:
            break
        ch = text[idx]
        if ch == "]":
            break
        if ch == ",":
            idx += 1
            continue
        try:
            value, idx = _DECODER.raw_decode(text, idx)
        except ValueError:
            break
        if not isinstance(value, dict):
            return items, False
        items.append(value)
    return items, True


def _wrapper_is_table(text: str, idx: int) -> bool:
    """Обёртка вида `{"data": [ {...}, ... ]}` → таблица. Дерево настроек → нет.

    Требуем ЕДИНСТВЕННЫЙ массив объектов и никаких непустых вложенных структур рядом:
    `{"meta": {...}, "rows": [...]}` неоднозначен, а неоднозначность идёт в словари.
    """
    n = len(text)
    found_table = False
    while True:
        idx = _skip_ws(text, idx)
        if idx >= n or text[idx] == "}":
            break
        if text[idx] == ",":
            idx += 1
            continue
        if text[idx] != '"':
            return False
        try:
            _key, idx = _DECODER.raw_decode(text, idx)
        except ValueError:
            break
        idx = _skip_ws(text, idx)
        if idx >= n or text[idx] != ":":
            break
        idx = _skip_ws(text, idx + 1)
        if idx >= n:
            break
        if text[idx] == "[":
            items, all_objects = _scan_array_objects(text, idx + 1)
            if not (all_objects and _uniform_objects(items)):
                return False
            if found_table:
                return False
            found_table = True
            try:
                _value, idx = _DECODER.raw_decode(text, idx)
            except ValueError:
                # Массив не влез в голову — значит он и есть тело файла.
                return True
            continue
        try:
            value, idx = _DECODER.raw_decode(text, idx)
        except ValueError:
            break
        if isinstance(value, dict | list) and value:
            return False
    return found_table


def _json_is_table(text: str) -> bool:
    idx = _skip_ws(text, 0)
    if idx >= len(text):
        return False
    if text[idx] == "[":
        items, all_objects = _scan_array_objects(text, idx + 1)
        return all_objects and _uniform_objects(items)
    if text[idx] == "{":
        return _wrapper_is_table(text, idx + 1)
    return False


def _jsonl_is_table(text: str, *, truncated: bool) -> bool:
    """JSONL — таблица, если строки это объекты со схожими ключами.

    ⚠️ Последнюю строку головы отбрасываем при обрыве: она наверняка обрезана, и её
    непарсимость сказала бы «не таблица» про совершенно нормальный файл.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    if truncated and lines:
        lines = lines[:-1]
    items: list[dict] = []
    for line in lines:
        if not line:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            return False
        if not isinstance(value, dict):
            return False
        items.append(value)
        if len(items) >= _MAX_PROBE_ITEMS:
            break
    return _uniform_objects(items)


def _rows_in_head(text: str, *, truncated: bool) -> list[str]:
    lines = text.splitlines()
    if truncated and lines:
        lines = lines[:-1]
    return [ln for ln in lines if ln.strip()]


def _delimited_is_table(text: str, *, truncated: bool, require_delimiter: bool) -> bool:
    """Разделённый текст. Одна строка — это НЕ таблица (заголовок без строк).

    Для `.txt` дополнительно требуем разделитель с одинаковым числом вхождений: иначе
    проза уезжала бы в SQL просто потому, что DuckDB умеет читать `.txt` как CSV.
    """
    rows = _rows_in_head(text, truncated=truncated)
    if len(rows) < 2:
        return False
    if not require_delimiter:
        return True
    probe = rows[:_MAX_PROBE_LINES]
    for delim in _DELIMITERS:
        counts = [row.count(delim) for row in probe]
        if counts[0] < 1:
            continue
        same = sum(1 for c in counts if c == counts[0])
        if same >= max(2, int(len(counts) * 0.8)):
            return True
    return False


def looks_tabular(
    filename: str, head: bytes | str | None, *, truncated: bool | None = None
) -> bool:
    """Стоит ли этот файл отдавать в SQL (`analyze_data`).

    ``head`` — первые ``HEAD_BYTES`` байт; ``None`` означает «прочитать не удалось».
    ``truncated`` — была ли голова обрезана; по умолчанию выводится из её размера.
    """
    ext = _ext(filename)
    if ext in FORMAT_IS_TABLE:
        return True
    if ext not in SHAPE_DECIDES:
        return False
    if head is None:
        # Содержимое недоступно — судить не по чему, остаётся только имя. Для `.json`
        # и `.txt` имя не говорит НИЧЕГО, и вера ему вернула бы ровно тот дефект, ради
        # которого этот модуль написан; `.csv` объявляет данные сам.
        logger.debug("форма файла %s не определена: содержимое недоступно", filename)
        return ext in NAME_DECLARES_TABLE

    raw = head.encode("utf-8", "ignore") if isinstance(head, str) else head
    if truncated is None:
        truncated = len(raw) >= HEAD_BYTES
    text = raw.decode("utf-8", "ignore")
    if not text.strip():
        return False

    if ext == ".json":
        return _json_is_table(text)
    if ext in (".jsonl", ".ndjson"):
        return _jsonl_is_table(text, truncated=truncated)
    if ext in (".csv", ".tsv"):
        return _delimited_is_table(text, truncated=truncated, require_delimiter=False)
    return _delimited_is_table(text, truncated=truncated, require_delimiter=True)
