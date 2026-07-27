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
MAX_WRITE_BYTES = 1024 * 1024
MAX_LIST_ENTRIES = 500
MAX_GREP_MATCHES = 200


class UnsafePath(Exception):
    """Путь ведёт за пределы корня песочницы."""


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
    raw = str(path or "").strip()
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
