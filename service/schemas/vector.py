"""Контракт ``/vector/*`` сайдкара agents (Фаза 3).

Векторное хранилище (обёртка Qdrant) живёт в домене и считает эмбеддинги через
мультипровайдерный слой — а им теперь владеет САЙДКАР. Поэтому индексация/поиск/снос
переезжают туда, а backend (upload, graph_api) становится HTTP-клиентом: иначе в Фазе 5,
когда домен уедет из backend, эти ручки остались бы с битым импортом.

Тела маленькие и плоские — кроме ``text`` при индексации, но документ и так уже прочитан
в память на стороне backend'а.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VectorIndexRequest(BaseModel):
    """Тело ``POST /vector/index``."""

    user_id: str
    filename: str
    text: str

    model_config = ConfigDict(extra="ignore")


class VectorSearchRequest(BaseModel):
    """Тело ``POST /vector/search``. ``top_k=None`` → дефолт хранилища."""

    user_id: str
    query: str
    top_k: int | None = Field(default=None, ge=1, le=100)

    model_config = ConfigDict(extra="ignore")


class VectorDeleteRequest(BaseModel):
    """Тело ``POST /vector/delete`` — снос ВСЕХ документов пользователя."""

    user_id: str

    model_config = ConfigDict(extra="ignore")


class MediaImageRequest(BaseModel):
    """Тело ``POST /media/describe-image``: байты картинки в base64."""

    content_b64: str
    content_type: str = "image/png"
    filename: str = "image.png"

    model_config = ConfigDict(extra="ignore")


class MediaAudioRequest(BaseModel):
    """Тело ``POST /media/transcribe``: байты аудио в base64."""

    content_b64: str
    filename: str = "audio.wav"

    model_config = ConfigDict(extra="ignore")
