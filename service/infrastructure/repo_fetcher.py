"""Ссылка на репозиторий → карта архитектуры.

Почему НЕ `git clone`: клонировать по произвольному URL, который прислал пользователь, —
это классический SSRF. Сервер пойдёт стучаться туда, куда ему сказали, включая внутреннюю
сеть. Поэтому:

* **белый список хостов** — только известные хостинги, и только https;
* **никакого git** — тянем готовый tar.gz архив по HTTPS (GitHub/GitLab/Bitbucket его
  отдают штатно). Заодно не нужен git-бинарь в образе, а `--depth 1` получается сам собой:
  архив и так без истории;
* **потолок размера при СКАЧИВАНИИ**, а не после: иначе «репозиторий» на 10 ГБ съел бы
  память до того, как мы успели бы его отвергнуть;
* **редиректы вручную**, с перепроверкой хоста на каждом шаге — иначе редирект увёл бы нас
  с разрешённого хоста куда угодно.

Сам разбор делает сайдкар graphify: tree-sitter AST, 36 языков, ни одного вызова LLM.
"""

from __future__ import annotations

import io
import logging
import re
import tarfile
from urllib.parse import urlparse

import httpx

from service.settings import config
from service.shared.agent_settings_port import runtime_settings
from service.shared.net_guard import UnsafeUrlError, assert_public_host

logger = logging.getLogger(__name__)

# Шаблоны архивов. Ref по умолчанию — HEAD ветки по умолчанию: угадывать main/master не
# нужно, хостинги это умеют сами.
_ARCHIVE_URLS = {
    "github.com": "https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}",
    "gitlab.com": "https://gitlab.com/{owner}/{repo}/-/archive/{ref}/{repo}-{ref}.tar.gz",
    "bitbucket.org": "https://bitbucket.org/{owner}/{repo}/get/{ref}.tar.gz",
}
_DEFAULT_REFS = {"github.com": "HEAD", "gitlab.com": "HEAD", "bitbucket.org": "HEAD"}

_PATH_RE = re.compile(r"^/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
_MAX_REDIRECTS = 3
_CHUNK = 64 * 1024


def allowed_hosts() -> set[str]:
    raw = runtime_settings.get_agents("repo_allowed_hosts", config.agents.repo_allowed_hosts) or ""
    return {h.strip().lower() for h in str(raw).split(",") if h.strip()}


def parse_repo_url(url: str) -> tuple[str, str, str] | None:
    """https://github.com/owner/repo → (host, owner, repo). None — это не репозиторий."""
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return None
    if parsed.scheme != "https":
        return None  # http и ssh не принимаем: только https и только по белому списку
    host = (parsed.hostname or "").lower()
    if host not in allowed_hosts() or host not in _ARCHIVE_URLS:
        return None
    match = _PATH_RE.match(parsed.path or "")
    if not match:
        return None  # ссылка на файл/issue/PR — это не репозиторий целиком
    return host, match.group(1), match.group(2)


def is_repo_url(url: str) -> bool:
    return parse_repo_url(url) is not None


async def fetch_repo_tarball(url: str) -> tuple[bytes, str]:
    """Скачать архив репозитория. → (tar.gz, "owner/repo").

    Бросает UnsafeUrlError на всё подозрительное — вызывающий трактует это как «обычная
    ссылка», а не как ошибку.
    """
    parsed = parse_repo_url(url)
    if not parsed:
        raise UnsafeUrlError("Не похоже на ссылку на репозиторий")
    host, owner, repo = parsed
    max_bytes = int(config.agents.repo_max_bytes or 50 * 1024 * 1024)

    archive_url = _ARCHIVE_URLS[host].format(owner=owner, repo=repo, ref=_DEFAULT_REFS[host])
    timeout = float(config.agents.repo_fetch_timeout_sec or 120.0)

    current = archive_url
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            target = urlparse(current)
            if target.scheme != "https":
                raise UnsafeUrlError(f"Недопустимая схема: {target.scheme}")
            # Хост проверяем на КАЖДОМ шаге: иначе редирект увёл бы нас с разрешённого
            # хоста на внутренний адрес.
            await assert_public_host(target.hostname or "")

            async with client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                    current = str(httpx.URL(current).join(resp.headers["location"]))
                    continue
                resp.raise_for_status()

                # Потолок проверяем ПО ХОДУ скачивания. Content-Length хостинги для
                # архивов не присылают (они генерируются на лету), так что верить нечему —
                # считаем сами и рвём соединение, как только превысили.
                buf = io.BytesIO()
                total = 0
                async for chunk in resp.aiter_bytes(_CHUNK):
                    total += len(chunk)
                    if total > max_bytes:
                        raise UnsafeUrlError(
                            f"Репозиторий больше лимита ({max_bytes // (1024 * 1024)} МБ)"
                        )
                    buf.write(chunk)
                return buf.getvalue(), f"{owner}/{repo}"

    raise UnsafeUrlError("Слишком много редиректов")


def strip_archive_root(tar_gz: bytes) -> bytes:
    """Убрать верхний каталог вида `repo-a1b2c3/`, который добавляют хостинги.

    Без этого источники узлов в графе выглядели бы как `repo-a1b2c3d/src/main.py` — с
    хэшем коммита в пути, который меняется при каждом обновлении и ничего не значит для
    пользователя.
    """
    src = io.BytesIO(tar_gz)
    out = io.BytesIO()
    with tarfile.open(fileobj=src, mode="r:gz") as tf, tarfile.open(fileobj=out, mode="w:gz") as tw:
        for member in tf:
            if not member.isfile():
                continue
            parts = member.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            payload = tf.extractfile(member)
            if payload is None:
                continue
            data = payload.read()
            info = tarfile.TarInfo(parts[1])
            info.size = len(data)
            tw.addfile(info, io.BytesIO(data))
    return out.getvalue()
