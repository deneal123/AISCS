"""Закрытая диагностика contract repair: без input из validation errors и секретов."""

from pydantic import ValidationError


def contract_feedback(error: ValueError | None) -> str:
    if isinstance(error, ValidationError):
        fields = {
            str(item["loc"][-1]) for item in error.errors(include_input=False) if item.get("loc")
        }
        rules = []
        if "criterion_id" in fields:
            rules.append(
                "criterion_id содержит только строчные латинские буквы, цифры, _ и -; "
                "начинается с буквы. Имя файла с точкой и MAX_USERS не подходят как ID."
            )
        if "target" in fields:
            rules.append(
                "target — относительный путь без ./, .., обратных косых черт и префикса диска. "
                "Удаляй начальный ./, не добавляй его снова. "
                "Правильные примеры: main.py для файла в корне, src/main.py для вложенного файла. "
                "Сохрани имя запрошенного файла, не заменяй его именем из примера."
            )
        return " ".join(rules) or (
            "Структура полей не соответствует схеме функции; сохрани обязательные поля и типы."
        )
    return {
        "contract_document_target": (
            "Критерий pdf относится к уже выбранному проекту: target должен содержать "
            "его указанный относительный путь или пустую строку. Не выдумывай имя файла PDF "
            "и не выбирай другой проект."
        ),
        "contract_criteria_incompatible": (
            "Виды критериев не соответствуют задаче: analysis допускает только read; "
            "change требует хотя бы один file; document требует хотя бы один pdf. "
            "В IDE недопустим pdf, в PDF недопустимы file и command. "
            "Сохрани цель и требуемые результаты, не меняй права."
        ),
        "contract_criteria_duplicate": (
            "У каждого критерия должен быть уникальный criterion_id. "
            "Не удаляй обязательные результаты ради уникальности."
        ),
        "contract_question_unexpected": (
            "При needs_clarification=false question должен быть пустой строкой. "
            "Если действительно требуется решение пользователя, передай true и конкретный вопрос. "
            "Не переписывай исходный запрос в поле question."
        ),
        "contract_question_required": (
            "При needs_clarification=true нужен непустой конкретный вопрос пользователю. "
            "Если цель уже однозначна, используй false и пустую строку question."
        ),
    }.get(str(error), "")
