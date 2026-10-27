"""Provider-neutral schema for one source-backed video notes chunk."""

from copy import deepcopy

FUNCTION = "submit_video_notes"


def field(kind: str, description: str, **extra) -> dict:
    return {"type": kind, "description": description, **extra}


def obj(description: str, properties: dict) -> dict:
    return field("object", description, properties=properties, required=list(properties))


TOOL = {
    "type": "function",
    "function": {
        "name": FUNCTION,
        "description": "Передать подтверждённые источником заметки по фрагменту расшифровки.",
        "parameters": obj(
            "Структурированные заметки без выдуманных идентификаторов и текста источника.",
            {
                "sections": field(
                    "array",
                    "Тематические разделы, последовательно раскрывающие предоставленный фрагмент.",
                    minItems=1,
                    maxItems=8,
                    items=obj(
                        "Один тематический раздел.",
                        {
                            "title": field("string", "Краткий заголовок раздела."),
                            "points": field(
                                "array",
                                "Тезисы раздела, подтверждённые источником.",
                                minItems=1,
                                maxItems=8,
                                items=obj(
                                    "Одно утверждение и подтверждающие фрагменты источника.",
                                    {
                                        "evidence": field(
                                            "array",
                                            "От одного до четырёх фрагментов-подтверждений.",
                                            minItems=1,
                                            maxItems=4,
                                            items=obj(
                                                "Одна точная цитата и от одного до четырёх "
                                                "последовательных идентификаторов реплик.",
                                                {
                                                    "cue_ids": field(
                                                        "array",
                                                        "От одного до четырёх последовательных "
                                                        "идентификаторов реплик с цитатой.",
                                                        minItems=1,
                                                        maxItems=4,
                                                        items=field("string", "ID реплики."),
                                                    ),
                                                    "quote": field(
                                                        "string",
                                                        "Точный непрерывный отрывок "
                                                        "выбранных реплик, соединённых "
                                                        "пробелами. Не менее 12 символов, "
                                                        "кроме случая короткой реплики.",
                                                    ),
                                                },
                                            ),
                                        ),
                                        "text": field(
                                            "string",
                                            "После выбора подтверждений напиши одно краткое "
                                            "фактическое утверждение, следующее из них. Сохрани "
                                            "подсчитываемый объект, условия и отрицания; "
                                            "без оценок и обобщений на основе частного примера.",
                                            minLength=1,
                                            maxLength=300,
                                        ),
                                    },
                                ),
                            ),
                        },
                    ),
                )
            },
        ),
    },
}


def tool_for(cue_ids: tuple[str, ...], quotes: tuple[str, ...] = ()) -> dict:
    """Constrain identifiers to this exact source part, not model-invented IDs."""
    tool = deepcopy(TOOL)
    sections = tool["function"]["parameters"]["properties"]["sections"]["items"]
    points = sections["properties"]["points"]["items"]
    evidence = points["properties"]["evidence"]["items"]
    evidence["properties"]["cue_ids"]["items"]["enum"] = list(cue_ids)
    if quotes:
        evidence["properties"]["quote"]["enum"] = list(dict.fromkeys(quotes))
        evidence["properties"]["quote"]["description"] = (
            "Выбери точный текст реплики из enum. Не исправляй слова и пунктуацию. "
            "Выбранные последовательные идентификаторы реплик должны охватывать эту цитату."
        )
    return tool


def grouped_tool_for(groups: dict[str, tuple[tuple[str, str], ...]]) -> dict:
    """Each mandatory scope has its own literal source enum and bounded sections."""
    tool = deepcopy(TOOL)
    properties = {}
    for name, cues in groups.items():
        scope = tool_for(tuple(cid for cid, _ in cues), tuple(text for _, text in cues))
        parameters = scope["function"]["parameters"]
        section = parameters["properties"]["sections"]["items"]
        section["properties"]["points"]["maxItems"] = 3
        parameters = obj(
            f"Один основной раздел с подтверждениями только для части {name}.",
            {"primary": section},
        )
        parameters["additionalProperties"] = False
        properties[name] = parameters
    tool["function"]["parameters"] = obj(
        "Для каждой предоставленной части источника обязательны свои подтверждённые заметки.",
        properties,
    )
    return tool
