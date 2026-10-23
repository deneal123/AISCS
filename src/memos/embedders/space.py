"""Идентичность пространства проходит вместе с вектором, а не через глобальный флаг."""

import re


class SpaceVector(list):
    def __init__(self, values, space: str):
        if not re.fullmatch(r"[0-9a-f]{32}", space):
            raise ValueError("invalid_embedding_space")
        super().__init__(values)
        self.space = space


def attach_space(metadata, vector):
    space = getattr(vector, "space", None)
    if space:
        metadata["embedding_space"] = space
    return metadata
