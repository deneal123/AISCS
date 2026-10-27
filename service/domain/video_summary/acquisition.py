"""Private source failures with deterministic user-facing recovery messages."""

from dataclasses import dataclass

KEY = "video.source_failure"
MESSAGES = {
    "source_rate_limited": "Источник ограничил получение речи. "
    "Попробуйте позже или загрузите аудиофайл.",
    "source_access_challenge": "Получить речь через доступные маршруты не удалось: "
    "источник требует авторизации. Можно загрузить видео или аудиофайл.",
    "source_access_denied": "Источник запретил получение речи через доступные маршруты. "
    "Можно загрузить видео или аудиофайл.",
}


@dataclass(frozen=True, slots=True)
class VideoSourceFailure:
    code: str


def record_source_failure(code: str) -> None:
    from service.domain.execution.context import current_execution

    execution = current_execution()
    if code in MESSAGES and execution is not None:
        execution.artifacts.publish(KEY, VideoSourceFailure(code), replace=True)


def source_failure_message(execution) -> str | None:
    failure = execution.artifacts.get(KEY, VideoSourceFailure)
    return MESSAGES.get(failure.code) if failure is not None else None


def clear_source_failure() -> None:
    from service.domain.execution.context import current_execution

    execution = current_execution()
    if execution is not None:
        execution.artifacts.discard(KEY)
