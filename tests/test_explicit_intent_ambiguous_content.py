import pytest

from service.domain.routing.explicit_intent import explicit_requested_tool


@pytest.mark.parametrize(
    "text",
    ["Напиши статью про Python", "Создай статью о рынке ИИ", "Write an article about Python"],
)
def test_article_request_without_file_format_is_not_document_generation(text: str) -> None:
    assert explicit_requested_tool(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Подготовь статью в PDF про Python",
        "Создай статью в DOCX о рынке ИИ",
        "Write an article as a PDF file",
    ],
)
def test_explicit_article_file_or_format_routes_to_document_generation(text: str) -> None:
    assert explicit_requested_tool(text) == "pdf_gen"


@pytest.mark.parametrize(
    "text",
    [
        "Сделай транскрипцию видео https://www.youtube.com/watch?v=sXKnmgmbkoE в файл",
        "Подготовь файл с расшифровкой https://youtu.be/example",
        "Создай файл с транскриптом https://youtu.be/example",
        "Создай PDF транскрипт https://youtu.be/example",
    ],
)
def test_video_transcript_request_is_not_routed_to_pdf_generation(text: str) -> None:
    assert explicit_requested_tool(text) is None


def test_non_video_pdf_transcript_still_routes_to_pdf_generation() -> None:
    assert explicit_requested_tool("Создай PDF транскрипт аудиозаписи") == "pdf_gen"
