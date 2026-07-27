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
from files import MAX_WRITE_BYTES, UnsafePath, safe_path
from net_guard import UnsafeUrlError, assert_public_host

logger = logging.getLogger("workspace-sidecar.import")

# Потолок на ОДИН файл и на весь импорт. Квота песочницы — про диск; эти два — про то,
# сколько мы готовы прокачать через себя, не занимая память процесса на всех арендаторов.
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILES = 20
DOWNLOAD_TIMEOUT_SEC = 60.0


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
        raise ImportRefused("источник не ответил") from exc
    if 300 <= response.status_code < 400:
        raise ImportRefused("редирект не поддерживается")
    if response.status_code >= 400:
        raise ImportRefused(f"источник ответил {response.status_code}")
    data = response.content or b""
    if len(data) > MAX_FILE_BYTES:
        raise ImportRefused(f"файл больше {MAX_FILE_BYTES} байт")
    return data


def write_command(root: str, name: str, data: bytes) -> str:
    """Команда записи скачанного файла внутрь песочницы.

    ⚠️ Содержимое едет base64 в аргументе команды — как и у обычной записи. Потолок
    `MAX_WRITE_BYTES` тот же: единая граница на «сколько влезает в один вызов».
    """
    try:
        target = safe_path(root, name)
    except UnsafePath as exc:
        raise ImportRefused(str(exc)) from exc
    payload = base64.b64encode(data).decode("ascii")
    if len(payload) > MAX_WRITE_BYTES * 2:
        raise ImportRefused(f"файл больше {MAX_WRITE_BYTES} байт для одного вызова")
    import shlex

    quoted, parent = shlex.quote(target), shlex.quote(target.rsplit("/", 1)[0] or root)
    return (
        f"mkdir -p {parent} && printf '%s' {shlex.quote(payload)} | base64 -d > {quoted} && "
        f'echo "__OK__ $(wc -c < {quoted})"'
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
