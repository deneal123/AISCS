"""Явная подготовка фиксированной модели; inference-контейнер не скачивает файлы."""

import os
from pathlib import Path

from ..service.domain.model import MODEL
from ..service.infrastructure.models.artifacts import ArtifactUnavailable, download


def main() -> int:
    try:
        download(MODEL, Path(os.environ.get("LOCAL_LLM_MODEL_DIR", "/models")))
    except ArtifactUnavailable as error:
        print(str(error), flush=True)
        return 1
    print("model_verified", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
