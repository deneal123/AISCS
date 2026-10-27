"""Документированный usage GigaChat embeddings находится у каждого элемента data."""

from openai.types.create_embedding_response import Usage


def normalize_embedding_response(response):
    data = response.model_dump()
    aggregate = data.get("usage")
    if isinstance(aggregate, dict) and type(aggregate.get("prompt_tokens")) is int:
        return response
    items = data.get("data") or []
    tokens = [(item.get("usage") or {}).get("prompt_tokens") for item in items]
    if not tokens or any(type(value) is not int or value < 0 for value in tokens):
        return response  # Отсутствующий расход не объявляем нулевым.
    count = sum(tokens)
    return response.model_copy(update={"usage": Usage(prompt_tokens=count, total_tokens=count)})
