"""Эмбеддинги через OpenAI-совместимый транспорт и общий шлюз GPTHub."""

import math
import os

from openai import AzureOpenAI as AzureClient
from openai import OpenAI as OpenAIClient

from memos.configs.embedder import UniversalAPIEmbedderConfig
from memos.embedders.base import BaseEmbedder
from memos.embedders.space import SpaceVector
from memos.embedders.transport_privacy import private_transport


def _sanitize_unicode(text: str) -> str:
    return (
        text.encode("utf-8", errors="surrogatepass")
        .decode("utf-8", errors="replace")
        .replace("\ufffd", "")
    )


class UniversalAPIEmbedder(BaseEmbedder):
    def __init__(self, config: UniversalAPIEmbedderConfig):
        self.provider = config.provider
        self.config = config
        timeout = float(os.getenv("MOS_EMBEDDER_TIMEOUT", "15"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("invalid_embedding_timeout")
        options = {"api_key": config.api_key, "timeout": timeout, "max_retries": 0}
        if self.provider == "openai":
            self.client = OpenAIClient(
                **options,
                base_url=config.base_url,
                default_headers=config.headers_extra or None,
            )
        elif self.provider == "azure":
            self.client = AzureClient(
                **options,
                azure_endpoint=config.base_url,
                api_version="2024-03-01-preview",
            )
        else:
            raise ValueError("embedding_provider_unsupported")
        # Резервный клиент не может безопасно писать в тот же индекс. Смена модели
        # выполняется общим шлюзом и сопровождается идентичностью пространства.
        if config.backup_client:
            raise ValueError("embedding_backup_requires_isolated_space")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if isinstance(texts, str):
            texts = [texts]
        texts = self._truncate_texts([_sanitize_unicode(text) for text in texts])
        if not texts:
            return []
        try:
            with private_transport():
                response = self.client.embeddings.create(
                    model=self.config.model_name_or_path,
                    input=texts,
                )
        except Exception:
            # Не включаем тело ответа или исходный текст в исключение/диагностику.
            raise ValueError("embedding_request_failed") from None
        if len(response.data) != len(texts):
            raise ValueError("embedding_count_mismatch")
        ordered = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(len(texts))):
            raise ValueError("embedding_index_mismatch")
        vectors = [item.embedding for item in ordered]
        space = getattr(response, "gpthub_embedding_space", None)
        if self.config.model_name_or_path == "gpthub-memory-embedding":
            if not isinstance(space, str):
                raise ValueError("embedding_space_missing")
            return [SpaceVector(vector, space) for vector in vectors]
        return vectors
