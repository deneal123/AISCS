"""Файловые операции внутри песочницы.

⚠️ ПОЧЕМУ ЗДЕСЬ, А НЕ В СЛОЕ АГЕНТОВ. Соблазн был сделать чтение и запись командами через
`exec` со стороны вызывающего — тогда сервису хватило бы одной ручки. Отказались по двум
причинам, и обе не про удобство:

🔴 Разбор пути обязан жить там же, где политика с её `root`. Проверка «путь внутри корня»,
выполненная у вызывающего, — это проверка, которую вызывающий может не сделать.

🔴 Чтение файла через поток вывода МОЛЧА обрезается потолком вывода команды. Молча
обрезанное чтение — это неверное чтение, а не короткое: модель получит половину файла и не
узнает об этом. Поэтому у чтения свой потолок и свой признак обрезки.

⚠️ Экранирование — в ОДНОМ месте (`_q`), а не в каждом вызывающем. Кавычки в имени файла,
которое придумала модель, иначе становятся выполнением произвольной команды.
"""

from __future__ import annotations

import base64
import posixpath
import shlex

# Потолок ЧТЕНИЯ отдельно от потолка вывода команды: файл читают, чтобы получить его
# целиком, а вывод сборки — чтобы увидеть, чем кончилось.
MAX_READ_BYTES = 256 * 1024
# Потолок ВЫГРУЗКИ артефакта отдельно от чтения: читает модель (и платит за токены), а
# выгружает backend в хранилище. 🔴 Больше не берём осознанно: base64 идёт через поток
# вывода команды, то есть целиком лежит в памяти процесса, обслуживающего всех арендаторов.
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024
MAX_WRITE_BYTES = 1024 * 1024
MAX_LIST_ENTRIES = 500
MAX_GREP_MATCHES = 200


class UnsafePath(Exception):
    """Путь ведёт за пределы корня песочницы."""


# 🔴 Байты, которых не может быть в аргументе команды. NUL завершает строку в syscall
# `exec`, и попытка передать его роняет создание процесса ЦЕЛИКОМ — наружу это уходило
# нечитаемым «Internal Server Error». Модель такую строку сочиняет запросто.
_FORBIDDEN_BYTES = ("\x00",)


def reject_control_bytes(text: str, what: str) -> str:
    """Отвергнуть то, что не может доехать до процесса. Отказ ВНЯТНЫЙ, а не 500."""
    value = str(text or "")
    if any(ch in value for ch in _FORBIDDEN_BYTES):
        raise UnsafePath(f"{what} содержит недопустимый нулевой байт")
    return value


def _q(value: str) -> str:
    return shlex.quote(str(value))


def safe_path(root: str, path: str) -> str:
    """Абсолютный путь внутри корня. Всё, что уходит наружу, — отказ.

    🔴 Нормализуем ДО сравнения: `a/../../etc` без нормализации выглядит начинающимся с
    корня и проходит проверку по префиксу.

    ⚠️ Сравниваем с корнем ПЛЮС разделитель: без него `/workspace-evil` считался бы
    лежащим внутри `/workspace`.
    """
    root_norm = posixpath.normpath("/" + str(root or "").strip("/"))
    raw = reject_control_bytes(path, "путь").strip()
    # ⚠️ Голый «/» — это «корень МОЕГО каталога» с точки зрения того, кто внутри песочницы.
    # Живой прогон: модель попросила `/`, получила отказ «за пределами песочницы» и сказала
    # пользователю, что не может читать файлы ВООБЩЕ. Отказ был формально верен и по делу
    # бесполезен. Прочие абсолютные пути (`/etc/passwd`) по-прежнему отвергаются.
    if raw == "/":
        raw = ""
    candidate = raw if raw.startswith("/") else posixpath.join(root_norm, raw)
    resolved = posixpath.normpath(candidate)
    if resolved != root_norm and not resolved.startswith(root_norm + "/"):
        raise UnsafePath(f"путь {path!r} ведёт за пределы песочницы")
    return resolved


def list_command(root: str, path: str, *, limit: int = MAX_LIST_ENTRIES) -> str:
    target = safe_path(root, path or root)
    # `-printf` есть не во всех образах; формат собираем сами из `find` + `ls`.
    return (
        f"find {_q(target)} -maxdepth 2 -mindepth 1 2>/dev/null | head -n {int(limit)} | "
        "while IFS= read -r p; do "
        'if [ -d "$p" ]; then echo "dir\t0\t$p"; '
        'else echo "file\t$(wc -c < "$p" 2>/dev/null || echo 0)\t$p"; fi; done'
    )


def read_command(root: str, path: str, *, max_bytes: int = MAX_READ_BYTES) -> str:
    """Прочитать файл в base64.

    ⚠️ base64, а не сырой текст: файл может быть не в UTF-8 и содержать что угодно, включая
    последовательности, которые поток вывода испортит. Плюс сразу видно, где кончился файл.
    """
    target = safe_path(root, path)
    return (
        f'if [ ! -f {_q(target)} ]; then echo "__MISSING__"; exit 0; fi; '
        f"head -c {int(max_bytes) + 1} {_q(target)} | base64 | tr -d '\\n'"
    )


def parse_read(output: str, *, max_bytes: int = MAX_READ_BYTES) -> tuple[str, bool]:
    """base64 → текст и признак обрезки. Признак ОБЯЗАТЕЛЕН: см. модульную шапку."""
    raw = (output or "").strip()
    if raw == "__MISSING__" or not raw:
        raise FileNotFoundError("файла нет")
    data = base64.b64decode(raw, validate=False)
    truncated = len(data) > max_bytes
    return data[:max_bytes].decode("utf-8", "replace"), truncated


def write_command(root: str, path: str, content: str) -> str:
    """Записать файл. Содержимое едет base64 — иначе кавычки и переводы строк ломают всё."""
    target = safe_path(root, path)
    payload = base64.b64encode(str(content or "").encode("utf-8")).decode("ascii")
    if len(payload) > MAX_WRITE_BYTES * 2:
        raise ValueError(f"содержимое больше {MAX_WRITE_BYTES} байт")
    parent = posixpath.dirname(target) or root
    return (
        f"mkdir -p {_q(parent)} && printf '%s' {_q(payload)} | base64 -d > {_q(target)} && "
        f'echo "__OK__ $(wc -c < {_q(target)})"'
    )


def grep_command(root: str, pattern: str, path: str, *, limit: int = MAX_GREP_MATCHES) -> str:
    """Поиск по содержимому. Шаблон уходит АРГУМЕНТОМ `-e`, а не частью команды."""
    target = safe_path(root, path or root)
    return (
        f"grep -rnI --exclude-dir=.git -e {_q(pattern)} {_q(target)} 2>/dev/null | "
        f"head -n {int(limit)}"
    )


def artifacts_command(root: str, *, limit: int = MAX_LIST_ENTRIES) -> str:
    """Что лежит в рабочем каталоге — плоским списком «размер, путь».

    ⚠️ Обход ВСЕЙ глубины, а не двух уровней как у `list`: артефакт мог родиться в
    подкаталоге, и не заметить его хуже, чем показать лишнее. Служебные каталоги
    инструментов исключены — иначе первый же `git init` или `pip install` завалил бы
    ответ тысячами файлов, которых пользователь не создавал.
    """
    target = safe_path(root, root)
    excludes = " ".join(
        f"-path {_q(target + '/' + name)} -prune -o" for name in (".git", "node_modules", ".venv")
    )
    return (
        f"find {_q(target)} {excludes} -type f -print 2>/dev/null | head -n {int(limit)} | "
        'while IFS= read -r p; do echo "$(wc -c < "$p" 2>/dev/null || echo 0)	$p"; done'
    )


def parse_artifacts(output: str, root: str, imported: set[str]) -> list[dict]:
    """Строки обхода → список артефактов. Импортированное исключается.

    🔴 Импортированный файл — НЕ артефакт: вернуть пользователю его же файл значит сообщить,
    что агент его создал. Сравниваем по пути ОТНОСИТЕЛЬНО корня: абсолютный путь внутри
    контейнера наружу не нужен и только путает.
    """
    out: list[dict] = []
    prefix = safe_path(root, root).rstrip("/") + "/"
    for line in (output or "").splitlines():
        size, _, path = line.partition("	")
        if not path:
            continue
        relative = path[len(prefix) :] if path.startswith(prefix) else path
        if relative in imported:
            continue
        try:
            out.append({"path": relative, "size": int(size or 0)})
        except ValueError:
            continue
    return out


def download_command(root: str, path: str) -> str:
    """Выгрузить артефакт целиком, в base64. Отличается от чтения только потолком."""
    return read_command(root, path, max_bytes=MAX_DOWNLOAD_BYTES)


def parse_download(output: str) -> tuple[str, bool]:
    """base64 КАК ЕСТЬ и признак обрезки.

    🔴 БЕЗ ДЕКОДИРОВАНИЯ В ТЕКСТ. `parse_read` разбирает байты как utf-8 с заменой битых —
    для `.xlsx`, картинки или архива это ПОРЧА, а не «неточность»: файл, отданный
    пользователю после такого разбора, не откроется. Артефакт обязан доехать побайтово.
    """
    raw = (output or "").strip()
    if raw == "__MISSING__" or not raw:
        raise FileNotFoundError("файла нет")
    # Обрезку определяем по длине base64: 4 символа на 3 байта.
    approx_bytes = len(raw) // 4 * 3
    return raw, approx_bytes > MAX_DOWNLOAD_BYTES
