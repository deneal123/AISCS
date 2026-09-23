from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.domain.subagents.audio import extract_audio_batch
from service.domain.subagents.audio.models import split_transcript
from service.domain.subagents.context_query import (
    QueryResolutionStatus,
    extract_constraints,
    preserves_constraints,
    resolve_query,
)
from service.domain.subagents.research import SourceRegistry, audit_citations
from service.domain.subagents.research.audit import strip_invalid_citations


def test_structured_multi_audio_preserves_long_content_timestamps_and_speakers() -> None:
    long_text = "A" * 14000
    context = SimpleNamespace(
        current_attachments=[
            {
                "kind": "audio",
                "name": "../meeting.mp3",
                "content": {
                    "language": "ru",
                    "segments": [
                        {"text": long_text, "start": 1.2, "end": 4.8, "speaker": " Alice "}
                    ],
                },
            },
            {"kind": "audio", "name": "second.wav", "content": "Второй транскрипт"},
        ]
    )

    task, batch = extract_audio_batch("Составь любые выводы", context)

    assert task == "Составь любые выводы"
    assert len(batch.transcripts) == 2
    assert batch.total_chars == len(long_text) + len("Второй транскрипт")
    assert "[00:01–00:04] Alice:" in batch.render_full()
    chunks = split_transcript(long_text, max_chars=2000)
    assert "".join(chunks) == long_text
    assert all(len(chunk) <= 2000 for chunk in chunks)


def test_source_registry_deduplicates_and_citation_audit_rejects_invented_links() -> None:
    registry = SourceRegistry()
    first = registry.add(
        url="HTTPS://Example.com:443/report?utm_source=private&a=1#secret",
        title="Report",
        content="Evidence body with enough text for registration.",
        content_kind="page",
    )
    duplicate = registry.add(
        url="https://example.com/report?a=1",
        title="Duplicate",
        content="Different body that must not create a duplicate URL.",
        content_kind="snippet",
    )
    registry.add(
        url="https://second.example/data",
        title="Second",
        content="Second independent evidence body with enough text.",
        content_kind="snippet",
    )

    assert first is duplicate
    assert len(registry.records) == 2
    assert "http" not in registry.synthesis_context()
    paragraph = "Данные исследования показывают изменение на 25 процентов. " * 4
    valid = audit_citations(f"{paragraph} [1]", registry)
    invalid = audit_citations(f"{paragraph} [999]", registry)
    assert valid.valid
    assert not invalid.valid and invalid.invalid_ids == (999,)
    assert "[999]" not in strip_invalid_citations("Факт [1], выдумка [999]", registry)
    assert "https://example.com/report?a=1" in registry.sources_section()


@pytest.mark.asyncio
async def test_query_resolution_falls_back_when_model_drops_exact_constraints(monkeypatch) -> None:
    query = "Найди данные об Acme Corp за 2025, но не цитату «internal marker»"
    context = SimpleNamespace(
        history_messages=[{"role": "user", "content": "Мы обсуждали отчёт Acme Corp."}]
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"query":"отчёт компании"}'))],
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1),
    )

    async def completion(**kwargs):
        return response

    monkeypatch.setattr(
        "service.domain.subagents.context_query.create_chat_completion",
        completion,
    )
    resolution = await resolve_query(query, context, "model")

    constraints = extract_constraints(query)
    assert not preserves_constraints("отчёт компании", constraints)
    assert resolution.status is QueryResolutionStatus.INVALID
    assert resolution.query == query
    assert "internal marker" not in repr(resolution.bounded_metadata())
