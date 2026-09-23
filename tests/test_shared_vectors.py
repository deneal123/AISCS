"""Конформанс по ОБЩИМ ВЕКТОРАМ: копии у двух сервисов не должны разойтись.

`net_guard`, `token_estimate` и `model_class` намеренно раздвоены — общий пакет ради
сотни строк stdlib связал бы релизы двух сервисов. Но молча разойтись им нельзя:

* `net_guard` — SSRF-защита. Отставшая копия пропустит адрес, который вторая уже
  считает внутренним. Это дыра, а не расхождение стиля.
* `token_estimate` — у backend есть путь, где оценка СТАНОВИТСЯ списанием (провайдер
  не вернул usage → списываем по резерву).
* `model_class` — у backend по нему фолбэк-цена, у сайдкара подбор при фейловере.

Механизм вместо общего кода: файл векторов лежит у КАЖДОЙ стороны, оба теста гоняют
свою реализацию против своей копии, а CI суперпроекта сверяет файлы ПОБАЙТОВО. Правка
на одной стороне без второй падает громко и в момент правки, а не когда-нибудь потом.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from service.shared.model_class import classify_model, cost_rank
from service.shared.net_guard import UnsafeUrlError, assert_public_host
from service.shared.token_estimate import estimate_tokens

_VECTORS = pathlib.Path(__file__).resolve().parent / "vectors"


def _load(name: str) -> list[dict]:
    return json.loads((_VECTORS / f"{name}.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _load("token_estimate_vectors"))
def test_token_estimate(case: dict) -> None:
    assert estimate_tokens(case["text"]) == case["tokens"], (
        f"оценка разошлась с вектором на {case['text'][:40]!r}"
    )


@pytest.mark.parametrize("case", _load("model_class_vectors"))
def test_model_class(case: dict) -> None:
    assert classify_model(case["model"]) == case["class"]
    assert cost_rank(case["model"]) == case["cost_rank"]


@pytest.mark.parametrize("case", _load("net_guard_vectors"))
@pytest.mark.asyncio
async def test_net_guard(case: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверяем ВЕРДИКТ по адресу: DNS подменяем, иначе тест зависел бы от сети."""
    addr = case["address"]
    family = 10 if ":" in addr else 2  # AF_INET6 / AF_INET

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(family, 1, 6, "", (addr, 0))]

    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)

    if case["safe"]:
        await assert_public_host("example.test")
    else:
        with pytest.raises(UnsafeUrlError):
            await assert_public_host("example.test")
