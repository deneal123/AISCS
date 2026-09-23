"""Tests for markdown-safe streaming chunking and guardrail-in-metadata."""

import pytest

from service.domain.subagents.base import BaseSubAgent
from service.domain.text_stream import iter_stream_chunks


def test_iter_stream_chunks_preserves_content_exactly():
    src = (
        "Заголовок\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        + "```python\n"
        + "print(1)\n" * 50
        + "```\n\nКонец."
    )
    chunks = list(iter_stream_chunks(src, chunk_size=40))
    # Ключевой инвариант: склейка чанков воспроизводит исходник посимвольно.
    assert "".join(chunks) == src
    assert len(chunks) > 1


def test_iter_stream_chunks_keeps_code_fence_intact():
    fence = "```python\n" + "x = 1\n" * 100 + "```\n"
    chunks = list(iter_stream_chunks(fence, chunk_size=50))
    assert "".join(chunks) == fence
    # Обе границы fence (```) в одном чанке — блок не разорван.
    fence_chunks = [c for c in chunks if "```" in c]
    assert len(fence_chunks) == 1


def test_iter_stream_chunks_table_rows_not_split():
    table = "| col1 | col2 |\n|------|------|\n| aaaa | bbbb |\n| cccc | dddd |\n"
    chunks = list(iter_stream_chunks(table, chunk_size=10))
    assert "".join(chunks) == table
    # Флаш только на границах строк -> строки таблицы целые.
    assert all(c.endswith("\n") for c in chunks)


def test_iter_stream_chunks_empty():
    assert list(iter_stream_chunks("")) == []


class _TinySubAgent(BaseSubAgent):
    def __init__(self):
        super().__init__(name="tiny", instructions="x", model_settings={})

    async def process(self, user_input, context):  # pragma: no cover - не используется
        if False:
            yield None


@pytest.mark.asyncio
async def test_stream_chunks_put_guardrail_in_metadata_not_text(monkeypatch):
    agent = _TinySubAgent()

    async def _guard(_text):
        return {"fact_check": {"tripwire": True, "info": {}}}

    monkeypatch.setattr(agent, "_evaluate_output_guardrail", _guard)

    events = []
    async for ev in agent.stream_text_chunks("Полезный ответ без предупреждений. " * 20):
        events.append(ev)

    joined = "".join(str(e.data or "") for e in events)
    # Предупреждение НЕ должно попадать в текст (ломало бы markdown и дублировалось).
    assert "⚠️" not in joined
    # Но guardrail-результат должен быть в metadata (один раз, на первом чанке).
    flagged = [e for e in events if e.metadata.get("guardrails", {}).get("fact_check")]
    assert len(flagged) == 1
    assert flagged[0].metadata["guardrails"]["fact_check"]["tripwire"] is True
