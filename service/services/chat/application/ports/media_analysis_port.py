from __future__ import annotations

from abc import ABC, abstractmethod


class MediaAnalysisPort(ABC):
    @abstractmethod
    async def analyze_image(self, content_bytes: bytes, content_type: str, filename: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def transcribe_audio(
        self,
        content_bytes: bytes,
        filename: str,
        *,
        mode: str = "local",
        model: str | None = None,
        # 🔴 Потолок длительности, выведенный из ОСТАТКА кредитов. Без него гейт загрузки
        # проверял лишь наличие денег: один кредит на счету пропускал часовую расшифровку
        # за 1000 — разницу платила платформа (замерено).
        max_duration_sec: float | None = None,
    ) -> str:
        raise NotImplementedError
