from __future__ import annotations

from abc import ABC, abstractmethod


class DocumentParsingPort(ABC):
    """Парсинг документа в markdown, пригодный для контекста LLM.

    Реализация — сайдкар opendataloader (PDF + office через LibreOffice). Контракт
    намеренно fail-open: `parse` возвращает пустую строку, если распарсить не вышло,
    и вызывающий код падает на legacy-путь (PyPDF2/python-docx), а не на ошибку.
    """

    @abstractmethod
    def supports(self, filename: str) -> bool:
        """Берётся ли этот формат сайдкаром (иначе — старый путь)."""
        raise NotImplementedError

    @abstractmethod
    async def parse(self, content_bytes: bytes, filename: str) -> str:
        """→ markdown, либо пустая строка при любой неудаче."""
        raise NotImplementedError
