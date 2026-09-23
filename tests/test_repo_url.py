"""Разбор репозитория по ссылке — и защита от SSRF.

Клонировать по произвольному URL, который прислал пользователь, — это классический SSRF:
сервер пойдёт стучаться туда, куда ему сказали, включая внутреннюю сеть. Поэтому белый
список хостов, только https, потолок размера ПРИ скачивании и перепроверка хоста на каждом
редиректе.
"""

import io
import tarfile

import pytest

from service.infrastructure import repo_fetcher
from service.shared.net_guard import UnsafeUrlError


# --------------------------------------------------------------------------- #
# Распознавание ссылки                                                         #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/psf/requests", ("github.com", "psf", "requests")),
        ("https://github.com/psf/requests.git", ("github.com", "psf", "requests")),
        ("https://github.com/psf/requests/", ("github.com", "psf", "requests")),
        ("https://gitlab.com/group/proj", ("gitlab.com", "group", "proj")),
    ],
)
def test_recognises_repository_urls(url, expected):
    assert repo_fetcher.parse_repo_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        # Не в белом списке — сервер туда не пойдёт.
        "https://evil.example.com/owner/repo",
        # Внутренние адреса: ровно то, ради чего белый список и существует.
        "https://169.254.169.254/owner/repo",
        "https://localhost/owner/repo",
        "https://10.0.0.5/owner/repo",
        # Не https.
        "http://github.com/psf/requests",
        "git@github.com:psf/requests.git",
        "ssh://github.com/psf/requests",
        # file:// — попытка прочитать локальный диск.
        "file:///etc/passwd",
        # Ссылка на файл/issue, а не на репозиторий целиком.
        "https://github.com/psf/requests/blob/main/README.md",
        "https://github.com/psf/requests/issues/1",
        "https://github.com/psf",
        "",
        None,
    ],
)
def test_rejects_everything_else(url):
    assert repo_fetcher.parse_repo_url(url) is None
    assert repo_fetcher.is_repo_url(url) is False


def test_host_allowlist_is_configurable(monkeypatch):
    monkeypatch.setattr(repo_fetcher, "allowed_hosts", lambda: {"gitlab.com"})
    assert repo_fetcher.is_repo_url("https://github.com/psf/requests") is False
    assert repo_fetcher.is_repo_url("https://gitlab.com/g/p") is True


# --------------------------------------------------------------------------- #
# Потолок размера — ПРИ скачивании                                             #
# --------------------------------------------------------------------------- #
class _Stream:
    """Бесконечный поток: имитирует «репозиторий» размером с диск."""

    status_code = 200
    headers: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    def raise_for_status(self):
        return None

    async def aiter_bytes(self, _size):
        while True:
            yield b"x" * 64 * 1024


class _Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    def stream(self, _method, _url):
        return _Stream()


@pytest.mark.asyncio
async def test_download_aborts_on_size_cap(monkeypatch):
    """Потолок проверяется ПО ХОДУ: иначе гигантский архив съел бы память до того,
    как мы успели бы его отвергнуть. Content-Length хостинги не присылают — архивы
    генерируются на лету, так что верить нечему."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "repo_max_bytes", 256 * 1024)
    monkeypatch.setattr(repo_fetcher.httpx, "AsyncClient", lambda **_kw: _Client())

    async def _ok(_host):
        return None

    monkeypatch.setattr(repo_fetcher, "assert_public_host", _ok)

    with pytest.raises(UnsafeUrlError, match="больше лимита"):
        await repo_fetcher.fetch_repo_tarball("https://github.com/psf/requests")


@pytest.mark.asyncio
async def test_redirect_to_internal_host_is_blocked(monkeypatch):
    """Редирект не должен уводить нас с разрешённого хоста на внутренний адрес —
    поэтому хост перепроверяется на КАЖДОМ шаге, а не только на первом."""
    seen: list[str] = []

    class _Redirect:
        status_code = 302
        headers = {"location": "https://169.254.169.254/secret"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    class _RedirectClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        def stream(self, _method, _url):
            return _Redirect()

    async def _guard(host):
        seen.append(host)
        if host != "codeload.github.com":
            raise UnsafeUrlError(f"внутренний адрес: {host}")

    monkeypatch.setattr(repo_fetcher.httpx, "AsyncClient", lambda **_kw: _RedirectClient())
    monkeypatch.setattr(repo_fetcher, "assert_public_host", _guard)

    with pytest.raises(UnsafeUrlError, match="внутренний адрес"):
        await repo_fetcher.fetch_repo_tarball("https://github.com/psf/requests")

    assert "169.254.169.254" in seen  # редирект действительно проверялся


# --------------------------------------------------------------------------- #
# Верхний каталог архива                                                       #
# --------------------------------------------------------------------------- #
def _tar(names: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tf:
        for name, body in names.items():
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return out.getvalue()


def test_archive_root_is_stripped():
    """Хостинги кладут всё в каталог `repo-<хэш>/`. Без снятия источники узлов в графе
    выглядели бы как `requests-a1b2c3d/src/main.py` — с хэшем коммита в пути, который
    меняется при каждом обновлении и ничего не значит."""
    payload = repo_fetcher.strip_archive_root(
        _tar({"requests-a1b2c3d/src/main.py": "x = 1", "requests-a1b2c3d/README.md": "# hi"})
    )
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
        names = sorted(tf.getnames())
    assert names == ["README.md", "src/main.py"]


# --------------------------------------------------------------------------- #
# Регресс: редиректы не должны падать                                          #
# --------------------------------------------------------------------------- #
def test_redirect_url_join_works():
    """Оба места (repo_fetcher и web_search) склеивали редирект через `.human_repr()` —
    метода, которого у httpx.URL нет вовсе (он из yarl). То есть ЛЮБОЙ редирект ронял
    разбор ссылки с AttributeError вместо того, чтобы за ним последовать. codeload
    редиректит регулярно, так что это не теория."""
    import httpx

    assert not hasattr(httpx.URL("https://a/b"), "human_repr")
    assert str(httpx.URL("https://a/b").join("/c")) == "https://a/c"


def test_no_module_calls_the_missing_method():
    """Проверяем отсутствие ВЫЗОВА `.human_repr()`, а не упоминания слова: в комментариях
    оно теперь есть намеренно."""
    import importlib
    from pathlib import Path

    # web_search уехал в сайдкар вместе с доменом (проверяется там же), здесь остался
    # repo_fetcher — им пользуется только backend.
    module = importlib.import_module("service.infrastructure.repo_fetcher")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert ".human_repr()" not in source, "repo_fetcher снова зовёт human_repr()"
