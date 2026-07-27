"""Импорт файлов внутрь песочницы: адрес и имя приходят СНАРУЖИ.

Обе величины подконтрольны вызывающему, значит обе — поверхность атаки: адрес ведёт в сеть
(SSRF), имя ведёт в файловую систему (побег из корня). Проверяем именно это, а не то, что
файл в принципе скачивается.
"""

from __future__ import annotations

import json
import pathlib
import shlex

import httpx
import pytest
from importer import MAX_FILES, ImportRefused, fetch, plan, write_command
from net_guard import UnsafeUrlError, assert_public_host

ROOT = "/workspace"


# --- общие с соседями векторы SSRF ----------------------------------------------------


def _vectors() -> list[dict]:
    path = pathlib.Path(__file__).resolve().parent / "vectors" / "net_guard_vectors.json"
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _vectors(), ids=lambda c: c["address"])
async def test_ssrf_verdicts_match_the_shared_vectors(case, monkeypatch) -> None:
    """⚠️ Векторы ОБЩИЕ с backend и agents и сверяются побайтово гейтом суперпроекта.

    Своя реализация у каждой стороны, но вердикт обязан совпадать: отставшая копия
    пропустит адрес, который вторая уже считает внутренним, — и это дыра, а не расхождение.
    """
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (case["address"], 0))]
    )
    if case["safe"]:
        await assert_public_host("example.test")
    else:
        with pytest.raises(UnsafeUrlError):
            await assert_public_host("example.test")


# --- адрес ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://files.example.com/x", "", "не ссылка"]
)
async def test_only_http_urls_are_accepted(url: str, monkeypatch) -> None:
    """⚠️ Проверяем ПРИЧИНУ отказа, а не сам отказ.

    Отказ дал бы и httpx: неизвестную схему он не умеет, и получилось бы «источник не
    ответил». То есть снятие проверки схемы осталось бы незамеченным, а пользователь вместо
    «нужна ссылка http(s)» читал бы про недоступный источник. Вклад этой проверки —
    ВНЯТНАЯ ПРИЧИНА, и тест обязан требовать именно её. Хост у ftp-случая публичный, а
    проверка адреса подменена: иначе отказ давала бы она.
    """
    monkeypatch.setattr("importer.assert_public_host", _ok)
    with pytest.raises(ImportRefused, match="http"):
        await fetch(url)


async def test_internal_host_is_refused(monkeypatch) -> None:
    """🔴 Ссылка приходит снаружи: без проверки это чтение внутреннего периметра.

    ⚠️ Скачивание подменено УСПЕШНЫМ. Иначе отказ давал бы неответивший `localhost`, и
    снятие самой SSRF-проверки не покраснело бы — тест смотрел бы не на то правило.
    """

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, content=b"secret")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(ImportRefused):
        await fetch("http://localhost:9000/bucket/file")


async def test_redirect_is_not_followed(monkeypatch) -> None:
    """🔴 3xx на внутренний хост — обход проверки адреса, сделанной до запроса."""

    async def fake_get(self, url, **kwargs):
        return httpx.Response(302, headers={"Location": "http://127.0.0.1:9000/secret"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr("importer.assert_public_host", _ok)
    with pytest.raises(ImportRefused):
        await fetch("https://files.example.com/a.txt")


async def _ok(_host: str) -> None:
    return None


async def test_oversized_file_is_refused(monkeypatch) -> None:
    from importer import MAX_FILE_BYTES

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, content=b"x" * (MAX_FILE_BYTES + 1))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr("importer.assert_public_host", _ok)
    with pytest.raises(ImportRefused):
        await fetch("https://files.example.com/big.bin")


# --- имя ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["../../etc/cron.d/x", "/etc/passwd", "a/../../../root/.ssh/k"])
def test_file_name_cannot_escape_the_root(name: str) -> None:
    """🔴 Имя тоже приходит снаружи: «файл» с таким именем лёг бы мимо песочницы."""
    with pytest.raises(ImportRefused):
        write_command(ROOT, name, b"payload")


def test_name_with_shell_metacharacters_stays_one_argument() -> None:
    """Проверяем число АРГУМЕНТОВ, а не отсутствие подстроки: кавычки обезвреживают текст."""
    tokens = shlex.split(write_command(ROOT, "a; rm -rf /.txt", b"data"))
    assert "rm" not in tokens


def test_binary_content_survives_the_round_trip() -> None:
    import base64

    command = write_command(ROOT, "img.bin", b"\xff\xd8\xff\x00binary")
    payload = next(t for t in shlex.split(command) if len(t) > 8 and t.endswith("="))
    assert base64.b64decode(payload) == b"\xff\xd8\xff\x00binary"


# --- отбор ----------------------------------------------------------------------------


def test_entries_without_a_name_or_url_are_dropped_loudly() -> None:
    selected = plan([{"name": "a", "url": "http://x/a"}, {"name": "b"}, {"url": "http://x/c"}])
    assert [s["name"] for s in selected] == ["a"]


def test_file_count_is_capped() -> None:
    """Потолок числа файлов: импорт делит время и память с чужими прогонами."""
    selected = plan([{"name": f"f{i}", "url": f"http://x/{i}"} for i in range(MAX_FILES + 5)])
    assert len(selected) == MAX_FILES
