"""Общий слой OpenAI-совместимых провайдеров.

⚠️ У этого модуля не было НИ ОДНОГО теста, хотя через него идут три провайдера
(openai / openrouter / mws) — то есть большая часть трафика платформы. Он и появился-то
ради устранения расхождений между копиями (докстринг `openai_compatible.py:1-11`
называет конкретный случай: забытый `set_default_openai_api` в одном из четырёх), но сам
остался без сетки.

Тесты характеризующие: они фиксируют ТЕКУЩЕЕ поведение перед тем, как на этот слой
переедет фабрика провайдеров. Их задача — поймать изменение смысла, а не описать идеал.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.domain.client.providers import openai_compatible as oc


class _Recorder:
    """Клиент-дублёр: запоминает payload, с которым его позвали."""

    def __init__(self):
        self.chat_payload: dict | None = None
        self.completion_payload: dict | None = None
        self.embedding_payload: dict | None = None
        outer = self

        class _Completions:
            async def create(self, **kw):
                outer.chat_payload = kw
                return SimpleNamespace(ok=True)

        class _Chat:
            completions = _Completions()

        class _RawCompletions:
            async def create(self, **kw):
                outer.completion_payload = kw
                return SimpleNamespace(ok=True)

        class _Embeddings:
            async def create(self, **kw):
                outer.embedding_payload = kw
                return SimpleNamespace(ok=True)

        self.chat = _Chat()
        self.completions = _RawCompletions()
        self.embeddings = _Embeddings()


# --------------------------------------------------------------------------- #
# normalize_model_list                                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected", "why"),
    [
        ([{"id": "b"}, {"id": "a"}], ["a", "b"], "сортировка"),
        ([{"id": "a"}, {"id": "a"}], ["a"], "дедупликация"),
        ([{"id": "  a  "}], ["a"], "обрезка пробелов"),
        ([{"id": ""}, {"id": "   "}], [], "пустые id отбрасываются"),
        ([{"nope": 1}], [], "элемент без id"),
        ([SimpleNamespace(id="x")], ["x"], "атрибутный элемент, не только dict"),
        (None, [], "None вместо списка не роняет"),
        ([{"id": 42}], [], "нестроковый id отбрасывается"),
    ],
)
def test_normalize_model_list(raw, expected, why):
    assert oc.normalize_model_list(raw) == expected, why


# --------------------------------------------------------------------------- #
# Незаданный клиент — понятная ошибка, а не AttributeError                       #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("call", "kwargs"),
    [
        (oc.chat_completion, {"messages": [], "model": "m"}),
        (oc.completion, {"prompt": "p", "model": "m"}),
        (oc.embedding, {"text": "t", "model": "m"}),
    ],
    ids=["chat", "completion", "embedding"],
)
@pytest.mark.asyncio
async def test_missing_client_raises_named_error(call, kwargs):
    """⚠️ В тексте ошибки обязан быть ЛЕЙБЛ провайдера.

    Это сообщение видит инженер в логах при недоданном ключе; без имени провайдера
    оно бесполезно, когда провайдеров пять.
    """
    with pytest.raises(RuntimeError, match="ACME"):
        await call(None, "ACME", **kwargs)


# --------------------------------------------------------------------------- #
# chat_completion: необязательные параметры не протекают                        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_chat_sends_only_what_was_given():
    """None-параметры НЕ уезжают в payload.

    Провайдеры по-разному относятся к явному null: часть отвечает 400. Поэтому
    «не задано» и «задано как None» обязаны быть неразличимы на проводе.
    """
    client = _Recorder()

    await oc.chat_completion(client, "ACME", messages=[{"role": "user"}], model="m")

    assert client.chat_payload == {"model": "m", "messages": [{"role": "user"}]}


@pytest.mark.asyncio
async def test_chat_forwards_every_supported_knob():
    client = _Recorder()

    await oc.chat_completion(
        client,
        "ACME",
        messages=[],
        model="m",
        temperature=0.5,
        max_tokens=100,
        n=2,
        presence_penalty=0.1,
        frequency_penalty=0.2,
    )

    assert client.chat_payload == {
        "model": "m",
        "messages": [],
        "temperature": 0.5,
        "max_tokens": 100,
        "n": 2,
        "presence_penalty": 0.1,
        "frequency_penalty": 0.2,
    }


@pytest.mark.asyncio
async def test_chat_extra_carries_tools_and_can_override():
    """`extra` — это канал для tools/response_format/top_p и прочего.

    ⚠️ Он применяется ПОСЛЕДНИМ и потому может перекрыть явный параметр. Свойство
    неочевидное, поэтому закреплено: на нём держится передача tools и seed.
    """
    client = _Recorder()

    await oc.chat_completion(
        client,
        "ACME",
        messages=[],
        model="m",
        temperature=0.5,
        extra={"tools": [{"type": "function"}], "temperature": 0.9},
    )

    assert client.chat_payload["tools"] == [{"type": "function"}]
    assert client.chat_payload["temperature"] == 0.9, "extra обязан иметь приоритет"


@pytest.mark.asyncio
async def test_completion_sends_only_what_was_given():
    client = _Recorder()

    await oc.completion(client, "ACME", prompt="p", model="m", stop=["\n"])

    assert client.completion_payload == {"model": "m", "prompt": "p", "stop": ["\n"]}


@pytest.mark.asyncio
async def test_embedding_passes_text_as_input():
    """Поле называется `input`, а параметр — `text`: переименование легко потерять."""
    client = _Recorder()

    await oc.embedding(client, "ACME", text="привет", model="emb")

    assert client.embedding_payload == {"model": "emb", "input": "привет"}


# --------------------------------------------------------------------------- #
# make_http_client                                                              #
# --------------------------------------------------------------------------- #
def test_http_client_without_proxy(monkeypatch):
    monkeypatch.setattr(
        "service.domain.client.providers._http.build_proxy_url", lambda _name: "", raising=True
    )

    client = oc.make_http_client("acme", timeout=7.0)

    assert client.timeout.read == 7.0


def test_http_client_survives_broken_proxy_config(monkeypatch, caplog):
    """⚠️ Кривой прокси не должен лишать провайдера клиента совсем.

    Иначе одна опечатка в `AGENTS__PROXY_PROVIDERS`/URL выключала бы провайдера
    целиком — при том что без прокси он у части пользователей работает.
    """

    def _boom(_name):
        return "://это-не-url"

    monkeypatch.setattr(
        "service.domain.client.providers._http.build_proxy_url", _boom, raising=True
    )

    client = oc.make_http_client("acme", timeout=3.0)

    assert client is not None
    assert client.timeout.read == 3.0
