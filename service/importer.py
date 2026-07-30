"""Импорт файлов пользователя внутрь песочницы по презайнед-ссылке.

⚠️ ССЫЛКАМИ, А НЕ БАЙТАМИ. Файл весит десятки мегабайт, а тело запроса у этого сервиса
маленькое намеренно. Качает сайдкар — тот же приём, что у табличных файлов в слое агентов.

🔴 АДРЕС ПРИХОДИТ СНАРУЖИ, значит это SSRF-поверхность. Презайнед-ссылки нашего хранилища
переписаны на ПУБЛИЧНЫЙ адрес (иначе их не открыл бы браузер), поэтому проверка «хост
публичный» их пропускает и при этом закрывает внутренний периметр. Редиректы не ходим по
той же причине, что и в MCP: 3xx на внутренний хост — обход проверки.

⚠️ Имя файла тоже приходит снаружи и тоже разбирается `safe_path`: «имя» вида
`../../etc/cron.d/x` иначе кладёт файл мимо песочницы.
"""

from __future__ import annotations

import base64
import logging
from urllib.parse import urlparse

import httpx

from files import UnsafePath, safe_path
from net_guard import UnsafeUrlError, assert_public_host

logger = logging.getLogger("workspace-sidecar.import")

# Потолок на ОДИН файл и на весь импорт. Квота песочницы — про диск; эти два — про то,
# сколько мы готовы прокачать через себя, не занимая память процесса на всех арендаторов.
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILES = 20
DOWNLOAD_TIMEOUT_SEC = 60.0

# Файл уже лежит в песочнице — оставляем как есть. Отдельный маркер, а не молчание и не
# ошибка: это НОРМА (импорт повторяется каждый ход), но и не «положили заново».
EXISTS_MARKER = "__EXISTS__"


class ImportRefused(Exception):
    """Файл не взят: адрес небезопасен, имя ведёт наружу или размер за потолком."""


async def fetch(url: str, *, timeout_sec: float = DOWNLOAD_TIMEOUT_SEC) -> bytes:
    """Скачать файл, проверив адрес. Ошибки — одним исключением с человеческим текстом."""
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in ("http", "https"):
        raise ImportRefused("ссылка должна быть http(s)")
    try:
        await assert_public_host(parsed.hostname or "")
    except UnsafeUrlError as exc:
        raise ImportRefused(f"адрес не подходит: {exc}") from exc
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout_sec) as client:
            response = await client.get(str(url))
    except Exception as exc:  # noqa: BLE001
        # 🔴 ПРИЧИНУ НАЗЫВАЕМ. «Источник не ответил» одинаково покрывает не разрешившееся
        # имя, отказ TLS, обрыв и таймаут — а действия при них РАЗНЫЕ: первое означает, что
        # сайдкару сломали сеть, последнее — что источник медленный. Единственное, что
        # видел вызывающий, — эта строка, и по ней разобраться было нельзя ничем.
        logger.warning("не скачали %s: %s", parsed.hostname or "?", exc, exc_info=True)
        raise ImportRefused(f"источник не ответил: {type(exc).__name__}") from exc
    if 300 <= response.status_code < 400:
        raise ImportRefused("редирект не поддерживается")
    if response.status_code >= 400:
        raise ImportRefused(f"источник ответил {response.status_code}")
    data = response.content or b""
    if len(data) > MAX_FILE_BYTES:
        raise ImportRefused(f"файл больше {MAX_FILE_BYTES} байт")
    return data


def write_command(root: str, name: str, data: bytes) -> tuple[str, bytes]:
    """Команда записи скачанного файла внутрь песочницы.

    🔴 СУЩЕСТВУЮЩИЙ ФАЙЛ НЕ ПЕРЕЗАПИСЫВАЕТСЯ. Импорт идёт НЕ ОДИН РАЗ: список файлов
    диалога уезжает в песочницу на КАЖДОМ ходу, поэтому безусловная запись возвращала файл
    к тому виду, в котором он лежит в хранилище, — и стирала правки агента предыдущего
    хода. МОЛЧА. «Поправь договор» → агент правит → «теперь добавь пункт 5» → правки нет,
    и никто об этом не сказал ни человеку, ни модели. Замерено живьём: после второго
    импорта в файле снова `price = 100` вместо `price = 250`.

    Песочница — РАБОЧАЯ КОПИЯ, а хранилище — источник, из которого она однажды заведена.
    Повторный импорт нетронутого файла и так был бы пустой операцией (то же содержимое —
    ноль изменений в истории), так что пропуск существующего ничего не отнимает.

    ⚠️ Новая версия файла приезжает НОВОЙ записью хранилища и попадает в каталог под
    отличающимся именем (`договор (2).docx`) — конфликта с этим правилом нет.

    🔴 СОДЕРЖИМОЕ ИДЁТ ЧЕРЕЗ STDIN, А НЕ В АРГУМЕНТАХ, и это не оптимизация. Оно клалось
    base64 прямо в argv, а потолок ОДНОГО аргумента у Linux — 128 КБ (`MAX_ARG_STRLEN`), то
    есть ~96 КБ исходных байт. Заявленный потолок при этом стоял 1 МБ и до проверки дело не
    доходило: `execve` падал раньше с `OSError: Argument list too long`. Любой настоящий
    архив с кодом не импортировался ВООБЩЕ, а снаружи это выглядело как «песочница есть, а
    внутри пусто» — ровно то, на что пожаловался человек, загрузив `src.zip`.

    ⚠️ Возвращаем ПАРУ `(команда, содержимое)`: команда читает stdin, содержимое отдаётся
    драйвером.

    🔴 ПОТОЛОК ЗДЕСЬ ТОТ ЖЕ, ЧТО У СКАЧИВАНИЯ, и это вторая половина того же дефекта. Стоял
    `MAX_WRITE_BYTES` (1 МБ) — потолок ТЕЛА ЗАПРОСА на запись, к импорту отношения не
    имеющий: `fetch` пропускал 32 МБ, а запись их же отказывалась принять. Один импорт с
    двумя разными границами означал, что настоящий архив либо ронял `execve` (96 КБ…1.5 МБ),
    либо получал отказ вопреки разрешённому скачиванию. Граница на импорт ОДНА.
    """
    try:
        target = safe_path(root, name)
    except UnsafePath as exc:
        raise ImportRefused(str(exc)) from exc
    if len(data) > MAX_FILE_BYTES:
        raise ImportRefused(f"файл больше {MAX_FILE_BYTES} байт")
    import shlex

    quoted, parent = shlex.quote(target), shlex.quote(target.rsplit("/", 1)[0] or root)
    command = (
        f"if [ -e {quoted} ]; then echo {EXISTS_MARKER}; exit 0; fi; "
        f"mkdir -p {parent} && base64 -d > {quoted} && "
        f'echo "__OK__ $(wc -c < {quoted})"'
    )
    return command, base64.b64encode(data)


# Разворачивание архива. 🔴 Загруженный `.zip` давал КАРТУ репозитория для промпта, но
# файлов, которые можно открыть и поправить, из него не появлялось: в песочнице лежал
# архив. Разворачиваем в каталог рядом — рабочее место должно содержать дерево, а не
# коробку с ним.
MAX_UNPACKED_FILES = 400
MAX_UNPACKED_BYTES = 64 * 1024 * 1024


def unpack_command(root: str, name: str) -> str:
    """Развернуть загруженный архив в каталог рядом. Не архив — тихо ничего не делает.

    🔴 Разворачиваем ПИТОНОМ, а не `unzip`: его в образе рантайма нет, а сети у песочницы
    нет тем более. `zipfile` есть всегда — образ питоновский по построению.

    🔴 Каждый путь внутри архива проверяется на выход за каталог назначения (zip-slip):
    архив приносит пользователь, и `../../etc/passwd` внутри него — обычное дело.
    Потолки на число файлов и суммарный размер — от zip-бомбы.
    """
    import shlex

    target = safe_path(root, name)
    dest = target.rsplit(".", 1)[0] or f"{target}-unpacked"
    script = (
        "import os,sys,zipfile\n"
        "src,dst=sys.argv[1],sys.argv[2]\n"
        "if not zipfile.is_zipfile(src): print('__NOT_ARCHIVE__'); raise SystemExit(0)\n"
        "total=0; taken=0\n"
        "with zipfile.ZipFile(src) as z:\n"
        "    for info in z.infolist():\n"
        "        if info.is_dir(): continue\n"
        f"        if taken>={MAX_UNPACKED_FILES} or total>{MAX_UNPACKED_BYTES}:\n"
        "            print('__TRUNCATED__'); break\n"
        "        out=os.path.realpath(os.path.join(dst,info.filename))\n"
        "        if not out.startswith(os.path.realpath(dst)+os.sep): continue\n"
        "        os.makedirs(os.path.dirname(out),exist_ok=True)\n"
        "        with z.open(info) as fh, open(out,'wb') as w:\n"
        "            data=fh.read(); w.write(data)\n"
        "        total+=len(data); taken+=1\n"
        "print('__OK__',taken)\n"
    )
    return (
        f"mkdir -p {shlex.quote(dest)} && "
        f"python3 -c {shlex.quote(script)} {shlex.quote(target)} {shlex.quote(dest)}"
    )


def plan(items: list[dict] | None) -> list[dict]:
    """Отобрать, что вообще берём. Отказ ГРОМКИЙ: молча укоротившийся список выглядит
    как «файлов столько и было», и пользователь не узнает, что его файл не доехал."""
    selected: list[dict] = []
    for item in items or ():
        if len(selected) >= MAX_FILES:
            logger.warning("импорт: файлов больше %d — остальные не взяты", MAX_FILES)
            break
        name = str((item or {}).get("name") or "").strip()
        url = str((item or {}).get("url") or "").strip()
        if not name or not url:
            logger.warning("импорт: запись без имени или ссылки пропущена")
            continue
        selected.append({"name": name, "url": url})
    return selected
