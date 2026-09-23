from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.domain.documents import (
    DocumentIntent,
    DocumentRunOutcome,
    DocumentStage,
    author_semantic_draft_result,
    build_document_evidence_bundle,
    document_status_event,
    restore_authoring_checkpoint,
)
from service.domain.documents import authoring as authoring_module
from service.domain.documents.authoring_protocol import (
    SECTION_TOOL,
    compile_section_tool,
    response_arguments,
)
from service.domain.documents.outline import (
    DocumentOutline,
    DocumentOutlineSection,
    ensure_required_outline_sections,
    parse_document_outline_result,
)
from service.domain.documents.section_parser import parse_authored_section
from service.domain.subagents import pdf_generation
from service.events import EventSerializer, EventType
from service.schemas.agents import ModalityAttachment


def _intent(**changes) -> DocumentIntent:
    values = {
        "schema_version": 1,
        "request": "Подготовь статью по приложенным материалам",
        "kind": "article",
        "profile_id": "generic_article",
        "locale": "ru-RU",
        "mode": "camera_ready",
        "title": "Обзор",
        "audience": "читатели",
        "length_class": "standard",
        "required_sections": (),
        "citation_policy": "required",
        "presentation_density": "balanced",
        "legal_fields": (),
        "user_requirements": (),
    }
    values.update(changes)
    return DocumentIntent(**values)


def _response(arguments=None, *, function_name="submit_document_outline"):
    calls = []
    if arguments is not None:
        calls = [SimpleNamespace(function=SimpleNamespace(name=function_name, arguments=arguments))]
    return SimpleNamespace(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=calls))]
        )
    )


def test_native_gigachat_function_call_is_parsed_without_text_fallback() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=None,
                    function_call=SimpleNamespace(
                        name="submit_document_outline",
                        arguments={"title": "Обзор", "sections": []},
                    ),
                )
            )
        ]
    )

    assert response_arguments(response, "submit_document_outline") == {
        "title": "Обзор",
        "sections": [],
    }
    assert response_arguments(response, "another_function") is None


def _outline_arguments() -> dict:
    return {
        "title": "Обзор",
        "sections": [
            {
                "title": "Введение",
                "purpose": "Кратко изложить предоставленные материалы.",
                "block_kinds": ["section"],
                "source_ids": [],
            }
        ],
    }


def test_profile_sections_survive_a_full_model_outline() -> None:
    outline = DocumentOutline(
        "Обзор",
        tuple(
            DocumentOutlineSection(
                f"optional_{index:02d}",
                f"Дополнительный раздел {index}",
                "Дополнительный материал",
                ("paragraph",),
                (),
            )
            for index in range(1, 17)
        ),
    )

    normalized = ensure_required_outline_sections(
        outline,
        ("Аннотация", "Введение", "Заключение", "Литература"),
    )

    assert len(normalized.sections) == 16
    titles = [section.title for section in normalized.sections]
    assert {"Аннотация", "Введение", "Заключение", "Литература"}.issubset(titles)
    assert titles.index("Аннотация") < titles.index("Введение")
    assert titles.index("Заключение") < titles.index("Литература")


def test_outline_collapses_bilingual_semantic_duplicates() -> None:
    outline = DocumentOutline(
        "Review",
        (
            DocumentOutlineSection("a", "Introduction", "First", ("paragraph",), ()),
            DocumentOutlineSection("b", "Введение", "Duplicate", ("paragraph",), ()),
            DocumentOutlineSection("c", "Method", "Method", ("paragraph",), ()),
            DocumentOutlineSection("d", "METHODS", "Duplicate", ("paragraph",), ()),
            DocumentOutlineSection("e", "Conclusion", "End", ("paragraph",), ()),
            DocumentOutlineSection("f", "References", "Sources", ("paragraph",), ()),
        ),
    )

    normalized = ensure_required_outline_sections(
        outline,
        ("Аннотация", "Введение", "Заключение", "Литература"),
    )

    assert [section.title for section in normalized.sections] == [
        "Аннотация",
        "Введение",
        "Method",
        "Заключение",
        "Литература",
    ]


def _section_arguments(section_id: str, text: str = "Текст раздела") -> dict:
    return {
        "section_id": section_id,
        "blocks": [
            {
                "kind": "paragraph",
                "title": "Введение",
                "text": text,
                "items": [],
                "columns": [],
                "rows": [],
                "source_id": 0,
                "asset_path": "",
                "level": 1,
            }
        ],
    }


def test_section_protocol_does_not_require_model_owned_identifiers() -> None:
    parameters = SECTION_TOOL["function"]["parameters"]

    assert "section_id" not in parameters["properties"]
    assert parameters["required"] == ["blocks"]

    compiled = compile_section_tool({7, 2}, {"paragraph", "table", "section"})
    source_id = compiled["function"]["parameters"]["properties"]["blocks"]["items"]["properties"][
        "source_id"
    ]
    assert source_id["enum"] == [0, 2, 7]
    assert compiled["function"]["parameters"]["properties"]["blocks"]["items"]["properties"][
        "kind"
    ]["enum"] == ["paragraph", "table"]


def test_outline_parser_discards_unregistered_advisory_source_ids() -> None:
    raw = _outline_arguments()
    raw["sections"][0]["source_ids"] = ["unregistered-private-source"]

    outline, reason = parse_document_outline_result(raw, allowed_source_ids=frozenset())

    assert reason is None
    assert outline is not None
    assert outline.sections[0].source_ids == ()


def test_section_response_is_bound_to_the_trusted_outline_section() -> None:
    section = DocumentOutlineSection(
        section_id="section_01_trusted",
        title="Введение",
        purpose="Ввести тему",
        block_kinds=("paragraph",),
        source_ids=(),
    )
    blocks, failure, reason = parse_authored_section(
        _section_arguments("model_supplied_wrong_id"),
        section,
        None,
        document_kind="article",
    )
    arguments_without_id = _section_arguments("ignored")
    arguments_without_id.pop("section_id")
    rebound, rebound_failure, rebound_reason = parse_authored_section(
        arguments_without_id,
        section,
        None,
        document_kind="article",
    )

    assert failure is None
    assert reason is None
    assert blocks is not None
    assert rebound_failure is None
    assert rebound_reason is None
    assert rebound is not None
    assert [block.block_id for block in blocks] == [block.block_id for block in rebound]


def test_section_call_cannot_smuggle_a_second_document_outline() -> None:
    section = DocumentOutlineSection(
        section_id="trusted_method",
        title="Метод",
        purpose="Describe the method",
        block_kinds=("paragraph",),
        source_ids=(),
    )
    raw = _section_arguments("ignored")
    raw["blocks"][0]["kind"] = "section"

    blocks, failure, reason = parse_authored_section(
        raw,
        section,
        None,
        document_kind="article",
    )

    assert blocks is None
    assert failure == "draft_invalid"
    assert reason == "section_scope_violation"


def test_article_abstract_owns_its_paragraph_inside_the_abstract_block() -> None:
    section = DocumentOutlineSection(
        section_id="trusted_abstract",
        title="Аннотация",
        purpose="Summarize the article",
        block_kinds=("paragraph",),
        source_ids=(),
    )

    blocks, failure, reason = parse_authored_section(
        _section_arguments("ignored", "Краткое содержание"),
        section,
        None,
        document_kind="article",
    )

    assert failure is None
    assert reason is None
    assert blocks is not None
    assert [(block.kind, block.title, block.text) for block in blocks] == [
        ("section", "Аннотация", "Краткое содержание")
    ]


def test_current_markdown_attachment_becomes_private_bounded_evidence() -> None:
    marker = "S36_PRIVATE_ATTACHMENT_MARKER"
    bundle = build_document_evidence_bundle(
        [
            ModalityAttachment(
                kind="document",
                name="materialy-dlya-obzornoi-stati (1).md",
                file_id="5c6bd8d1-93bc-4988-a409-c0f75fd50d74",
                mime_type="text/markdown",
                digest="a" * 64,
                content=(
                    f"# Материалы\n\n{marker}\n\n"
                    "Источник: [Проверяемая статья](https://example.test/paper), 2025. "
                    "DOI 10.1000/example."
                ),
            )
        ],
        None,
    )

    assert bundle.has_materials is True
    assert bundle.has_bibliography is True
    assert marker in bundle.prompt_context()
    assert bundle.attachments[0].source_id == "att-aaaaaaaaaaaaaaaa"
    assert bundle.attachments[0].chunks[0].source_id == "att-aaaaaaaaaaaaaaaa-c001"
    assert bundle.bibliography.records[0].canonical_url == "https://example.test/paper"
    summary = bundle.summary()
    assert marker not in repr(summary)
    assert "materialy" not in repr(summary)
    assert "https://" not in repr(summary)


@pytest.mark.asyncio
async def test_invalid_authoring_protocol_gets_exactly_one_repair(monkeypatch) -> None:
    calls: list[dict] = []

    async def invalid_model_call(*_args, **kwargs):
        calls.append(kwargs)
        return _response()

    monkeypatch.setattr(authoring_module, "invoke_model_call", invalid_model_call)
    execution = SimpleNamespace(provider_snapshot=None)

    result = await author_semantic_draft_result(
        _intent(),
        "GigaChat-2",
        execution=execution,
        citations=None,
    )

    assert result.accepted is False
    assert result.failure_code == "draft_protocol"
    assert result.repair_used is True
    assert len(calls) == 2
    assert {call["model"] for call in calls} == {"GigaChat-2"}
    assert all(call["pin_provider"] is None for call in calls)


@pytest.mark.asyncio
async def test_protocol_repair_accepts_valid_second_round_without_regenerating(monkeypatch) -> None:
    responses = iter(
        (
            _response(),
            _response(_outline_arguments()),
            _response(
                _section_arguments("section_01_3d5b60c3dd"),
                function_name="submit_document_section",
            ),
        )
    )
    calls = 0

    async def model_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr(authoring_module, "invoke_model_call", model_call)
    result = await author_semantic_draft_result(
        _intent(citation_policy="none"),
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=None,
    )

    assert result.accepted is True
    assert result.repair_used is True
    assert calls == 3
    assert result.draft is not None
    assert result.draft.blocks[0].block_id.startswith("section_000_")


@pytest.mark.asyncio
async def test_authoring_stages_and_trusted_section_heading_are_deterministic(monkeypatch) -> None:
    paragraph = _section_arguments("section_01_3d5b60c3dd")
    paragraph["blocks"][0]["kind"] = "paragraph"
    responses = iter(
        (
            _response(_outline_arguments()),
            _response(paragraph, function_name="submit_document_section"),
        )
    )
    stages: list[str] = []

    async def model_call(*_args, **_kwargs):
        return next(responses)

    async def stage(value: str) -> None:
        stages.append(value)

    monkeypatch.setattr(authoring_module, "invoke_model_call", model_call)
    result = await author_semantic_draft_result(
        _intent(citation_policy="none"),
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=None,
        stage=stage,
    )

    assert result.accepted is True
    assert stages == ["outline", "section_authoring"]
    assert result.draft is not None
    assert [block.kind for block in result.draft.blocks] == ["section", "paragraph"]
    assert result.draft.blocks[0].title == "Введение"


@pytest.mark.asyncio
async def test_accepted_sections_are_checkpointed_and_shared_repair_budget_is_bounded(
    monkeypatch,
) -> None:
    outline = _outline_arguments()
    outline["sections"].append(
        {
            "title": "Заключение",
            "purpose": "Сформулировать итог.",
            "block_kinds": ["paragraph"],
            "source_ids": [],
        }
    )
    responses = iter(
        (
            _response(outline),
            _response(),
            _response(
                _section_arguments("section_01_3d5b60c3dd"),
                function_name="submit_document_section",
            ),
            _response(),
        )
    )
    calls = 0
    checkpoints = []

    async def model_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return next(responses)

    async def checkpoint(value):
        checkpoints.append(value.payload())

    monkeypatch.setattr(authoring_module, "invoke_model_call", model_call)
    result = await author_semantic_draft_result(
        _intent(citation_policy="none"),
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=None,
        checkpoint=checkpoint,
    )

    assert result.accepted is False
    assert result.repair_used is True
    assert result.accepted_sections == 1
    assert calls == 4
    assert [item["stage"] for item in checkpoints] == ["outline", "section_authoring"]
    assert len(checkpoints[-1]["blocks"]) == 2


@pytest.mark.asyncio
async def test_explicit_retry_resumes_after_last_accepted_section(monkeypatch) -> None:
    outline = _outline_arguments()
    outline["sections"].append(
        {
            "title": "Заключение",
            "purpose": "Сформулировать итог.",
            "block_kinds": ["paragraph"],
            "source_ids": [],
        }
    )
    first_responses = iter(
        (
            _response(outline),
            _response(
                _section_arguments("section_01_3d5b60c3dd"),
                function_name="submit_document_section",
            ),
            _response(),
            _response(),
        )
    )
    checkpoints = []

    async def first_call(*_args, **_kwargs):
        return next(first_responses)

    async def checkpoint(value):
        checkpoints.append(value.payload())

    monkeypatch.setattr(authoring_module, "invoke_model_call", first_call)
    first = await author_semantic_draft_result(
        _intent(citation_policy="none"),
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=None,
        checkpoint=checkpoint,
    )
    resume = restore_authoring_checkpoint(checkpoints[-1], citations=None, evidence=None)
    assert first.accepted is False
    assert resume is not None
    assert resume.accepted_section_ids == ("section_01_3d5b60c3dd",)

    calls = 0
    second_id = resume.outline.sections[1].section_id

    async def resumed_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        arguments = _section_arguments(second_id, "Итог")
        arguments["blocks"][0]["kind"] = "paragraph"
        return _response(arguments, function_name="submit_document_section")

    monkeypatch.setattr(authoring_module, "invoke_model_call", resumed_call)
    resumed = await author_semantic_draft_result(
        _intent(citation_policy="none"),
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=None,
        resume=resume,
    )

    assert resumed.accepted is True
    assert resumed.accepted_sections == 2
    assert calls == 1
    assert resumed.draft is not None
    assert len(resumed.draft.blocks) == 4
    assert resumed.draft.blocks[2].kind == "section"
    assert resumed.draft.blocks[2].title == "Заключение"


def test_pre_compile_authoring_failure_never_claims_technical_audit() -> None:
    message = pdf_generation.PDFGenerationAgent._failure_message(
        {"failure_code": "draft_protocol", "stage": "section_authoring"}
    )

    assert "структуру документа" in message
    assert "техническ" not in message.lower()
    assert "PDF собран" not in message


def test_compiler_failure_codes_map_to_honest_closed_stage() -> None:
    code, stage, retryable = pdf_generation._public_failure(
        {"failure_code": "audit_failed", "stage": "compile"}
    )

    assert (code, stage, retryable) == (
        "deterministic_audit_failed",
        DocumentStage.DETERMINISTIC_AUDIT,
        False,
    )
    assert "техническую проверку" in pdf_generation.PDFGenerationAgent._failure_message(
        {"failure_code": code}
    )


def test_document_status_is_bounded_and_does_not_project_private_values() -> None:
    event = document_status_event(
        "pdf_gen",
        DocumentStage.EVIDENCE,
        "ready",
        outcome=DocumentRunOutcome.DRAFT_READY,
        failure_code="unknown-private-marker",
        facts={"attachment_count": 1, "bibliography_complete": False},
    )

    assert event.metadata["kind"] == "document_status"
    assert "failure_code" not in event.metadata["document_status"]
    assert event.metadata["document_status"]["facts"] == {
        "attachment_count": 1,
        "bibliography_complete": False,
    }
    assert "unknown-private-marker" not in repr(event.metadata)


def test_ndjson_serializer_defensively_redacts_legacy_document_status() -> None:
    marker = "S36_PRIVATE_PROVIDER_BODY"
    payload = EventSerializer().serialize(
        event=SimpleNamespace(
            type=EventType.STATUS_UPDATE,
            agent_name="pdf_gen",
            data="safe",
            seq=1,
            metadata={
                "kind": "document_status",
                "document_status": {
                    "stage": "evidence",
                    "status": "ready",
                    "retryable": False,
                    "facts": {"attachment_count": 1, "private": marker},
                    "raw_response": marker,
                },
                "arguments": marker,
            },
        ),
        job_id="job",
    )

    assert payload["metadata"] == {
        "kind": "document_status",
        "document_status": {
            "stage": "evidence",
            "status": "ready",
            "retryable": False,
            "facts": {"attachment_count": 1},
        },
    }
    assert marker not in repr(payload)
