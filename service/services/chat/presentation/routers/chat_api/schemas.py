from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MessageRequest(BaseModel):
    # Empty text is accepted only together with a server-issued confirmation anchor.
    text: str = ""
    confirm_offer_id: str | None = Field(default=None, min_length=16, max_length=128)
    user_id: int | str | None = None
    model: str | None = None
    input_type: Literal["text", "image", "audio", "video"] | None = None
    web_search: bool = False
    deep_research: bool = False
    route_override: (
        Literal[
            "general",
            "web_search",
            "deep_research",
            "audio_transcribe",
            "image_gen",
            "pptx_gen",
            "pdf_gen",
        ]
        | None
    ) = None
    # 🔴 СОГЛАСИЕ НА ДОРОГОЕ, отдельным признаком, а не значением `route_override`.
    # Просмотр видео — ИНСТРУМЕНТ, а не маршрут: он не меняет, кто отвечает, он снимает
    # запор с признака контекста. Втиснув его в перечень маршрутов, мы получили бы имя,
    # которого среди них нет, и разошлись бы с реестром способностей.
    # ⚠️ Признак живёт ОДНО СООБЩЕНИЕ: «согласился один раз — смотрит всегда» означало бы,
    # что человек платит за каждый следующий ход своей первой кнопкой.
    watch_video: bool = False
    confirm_expensive_run: bool = False
    file_context: str = ""
    file_ids: list[str] = Field(default_factory=list)
    # Мультимодальные вложения: [{kind, name, content}], уже сведённые к тексту.
    attachments: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_text_or_confirmation(self) -> "MessageRequest":
        """An empty body is valid only when it claims a server-side offer."""

        if not self.text.strip() and not self.confirm_offer_id:
            raise ValueError("message text is required")
        return self


class MessageResponse(BaseModel):
    reply: str
    thread_id: str | None = None
    metadata: dict | None = None


class ThreadCreate(BaseModel):
    user_id: int | None = None
    title: str | None = None


class ThreadUpdate(BaseModel):
    title: str


class FeedbackRequest(BaseModel):
    content_key: str
    rating: str | None = None  # "up" | "down" | None(снять)


class TraceSaveRequest(BaseModel):
    content_key: str
    trace: dict


class ThreadResponse(BaseModel):
    thread_id: str
    title: str | None = None
    created_at: str | None = None


class ModelsResponse(BaseModel):
    models: list[str]


class UploadFileResponse(BaseModel):
    filename: str
    file_type: str
    # Таблица ли файл ПО СОДЕРЖИМОМУ (см. shared/tabular_shape.py). Расширение не годится:
    # `.json` носит и массив записей, и дерево настроек, а модальность у них разная.
    is_tabular: bool = False
    size: int
    extracted_text: str
    thread_id: str
    file_id: str
    content_sha256: str
    mime_type: str
    file_url: str
    file_key: str
    temp_file: bool
