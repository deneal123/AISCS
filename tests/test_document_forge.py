from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from service.domain.capabilities import get_spec, get_workflow
from service.domain.capabilities.tool_registry import get_tool_spec
from service.domain.documents import (
    normalize_brief,
    parse_authored_document,
    parse_authored_tool_response,
    render_literal_document,
    skill_for_profile,
)
from service.domain.documents.visual_audit import (
    _audit_tool_arguments,
    _messages,
    _page_has_visible_ink,
    _parse_result,
    _reconcile_blank_diagnostics,
)
from service.domain.subagents.pdf_generation import _can_retry_visual_failure


@pytest.mark.parametrize(
    ("prompt", "kind", "profile"),
    [
        ("Сделай презентацию по отчёту", "presentation", "beamer_16_9"),
        ("Подготовь договор оказания услуг", "legal", "legal_ru"),
        ("Оформи статью для IEEE", "article", "ieee_journal"),
        ("Собери AAAI paper in English", "article", "aaai_conference"),
        ("Напиши техническое задание", "report", "generic_report"),
        ("Сделай аккуратный PDF", "generic", "generic_document"),
    ],
)
def test_document_brief_selects_deterministic_profile(prompt, kind, profile) -> None:
    brief = normalize_brief(prompt)

    assert brief.kind == kind
    assert brief.profile_id == profile


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ('Создай PDF и напиши "тест"', "тест"),
        ("Создай PDF, где написано ровно: тест 2", "тест 2"),
    ],
)
def test_document_brief_extracts_explicit_literal(prompt: str, expected: str) -> None:
    brief = normalize_brief(prompt)

    assert brief.kind == "generic"
    assert brief.literal_text == expected


def test_literal_document_preserves_profile_preamble_and_exact_text() -> None:
    authored = render_literal_document(
        "\\documentclass{article}\n\\usepackage{gpthub-core}\n"
        "\\begin{document}\nTemplate\n\\end{document}",
        "тест & 2",
    )

    assert authored is not None
    assert "\\usepackage{gpthub-core}" in authored.main_tex
    assert "тест \\& 2" in authored.main_tex
    assert "\\Huge\\bfseries" in authored.main_tex
    assert "Template" not in authored.main_tex


def test_authored_document_requires_strict_json_and_safe_latex() -> None:
    valid = json.dumps(
        {
            "title": "Проверяемый документ",
            "main_tex": (
                "\\documentclass{article}\n\\begin{document}\n"
                + "Проверяемый текст. " * 10
                + "\\end{document}"
            ),
            "references_bib": "",
        },
        ensure_ascii=False,
    )

    parsed = parse_authored_document(valid)

    assert parsed is not None
    assert parsed.title == "Проверяемый документ"
    assert parse_authored_document(valid.replace("\\begin{document}", "\\write18{curl x}")) is None
    assert parse_authored_document("not json") is None
    assert parse_authored_document(json.dumps({"main_tex": "x"})) is None


def test_authored_document_accepts_exact_typed_function_payload() -> None:
    payload = {
        "title": "Тестовый документ",
        "document_body": "\\maketitle\n" + "Безопасный текст. " * 10,
        "references_bib": "",
    }
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="submit_document_source",
                                arguments=json.dumps(payload, ensure_ascii=False),
                            )
                        )
                    ]
                )
            )
        ]
    )

    parsed = parse_authored_tool_response(
        response,
        function_name="submit_document_source",
        scaffold_source=(
            "\\documentclass{article}\n"
            "\\usepackage[margin=25mm]{geometry}\n"
            "\\begin{document}\nTemplate\n\\end{document}"
        ),
    )

    assert parsed is not None
    assert parsed.title == "Тестовый документ"
    assert (
        parse_authored_tool_response(
            response,
            function_name="another_function",
            scaffold_source="\\begin{document}\n\\end{document}",
        )
        is None
    )
    assert "\\usepackage[margin=25mm]{geometry}" in parsed.main_tex
    assert "Template" not in parsed.main_tex


def test_authored_document_rejects_non_string_structured_fields() -> None:
    assert (
        parse_authored_document(
            {
                "title": "Document",
                "main_tex": ["\\documentclass{article}"],
                "references_bib": "",
            }
        )
        is None
    )


def test_visual_audit_accepts_only_one_bounded_function_result() -> None:
    payload = {
        "passed": False,
        "issues": [{"code": "visual_clipping", "page": 2}],
    }
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="submit_visual_audit",
                                arguments=payload,
                            )
                        )
                    ]
                )
            )
        ]
    )

    passed, diagnostics = _parse_result(_audit_tool_arguments(response), frozenset({1, 2}))

    assert passed is False
    assert diagnostics == [{"code": "visual_clipping", "page": 2, "count": 1}]


def test_visual_audit_rejects_text_instead_of_forced_function() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[], content="passed"))]
    )

    with pytest.raises(ValueError, match="invalid visual audit response"):
        _audit_tool_arguments(response)


def test_visual_audit_compatibility_parser_accepts_fenced_json() -> None:
    passed, diagnostics = _parse_result(
        '```json\n{"passed": true, "issues": []}\n```', frozenset({1})
    )

    assert passed is True
    assert diagnostics == []


def test_visual_audit_prompt_accepts_sparse_but_visible_document() -> None:
    messages = _messages([(1, b"png")])
    instruction = messages[1]["content"][0]["text"]

    assert "deliberately sparse page" in instruction
    assert "no visible document content exists at all" in instruction


def _png(*, visible: bool) -> bytes:
    image = Image.new("L", (640, 900), color=255)
    if visible:
        ImageDraw.Draw(image).rectangle((220, 420, 420, 470), fill=0)
    payload = BytesIO()
    image.save(payload, format="PNG")
    return payload.getvalue()


def test_visual_blank_diagnostic_is_rejected_only_for_a_visibly_nonblank_page() -> None:
    visible = _png(visible=True)
    blank = _png(visible=False)
    issues = [
        {"code": "visual_blank_page", "page": 1, "count": 1},
        {"code": "visual_blank_page", "page": 2, "count": 1},
        {"code": "visual_clipping", "page": 1, "count": 1},
    ]

    assert _page_has_visible_ink(visible) is True
    assert _page_has_visible_ink(blank) is False
    assert _reconcile_blank_diagnostics(issues, [(1, visible), (2, blank)]) == [
        {"code": "visual_blank_page", "page": 2, "count": 1},
        {"code": "visual_clipping", "page": 1, "count": 1},
    ]


def test_literal_document_is_not_rebuilt_after_visual_rejection() -> None:
    assert _can_retry_visual_failure(literal_text="test", visual_repairs=0) is False
    assert _can_retry_visual_failure(literal_text=None, visual_repairs=0) is True
    assert _can_retry_visual_failure(literal_text=None, visual_repairs=1) is False


def test_document_skills_cover_every_supported_profile() -> None:
    profile_ids = {
        "aaai_conference",
        "beamer_16_9",
        "generic_article",
        "generic_document",
        "generic_report",
        "ieee_journal",
        "legal_ru",
    }

    assert {skill_for_profile(item).profile_id for item in profile_ids} == profile_ids
    assert all(
        "семантический DocumentDraft" in skill_for_profile(item).system_instruction()
        for item in profile_ids
    )


def test_document_capabilities_are_compiled_and_pptx_is_hidden_alias() -> None:
    pdf = get_spec("pdf_gen")
    workflow = get_workflow("research_pdf_presentation")

    assert pdf is not None and pdf.confirm_by_default and pdf.cost_class == "expensive"
    assert get_spec("pptx_gen") is None
    assert workflow is not None
    assert tuple(step.agent for step in workflow.steps) == ("deep_research", "pdf_gen")

    for name in (
        "tex_profiles",
        "tex_project_create",
        "tex_project_status",
        "tex_profile_apply",
        "tex_compile",
        "tex_build_status",
        "tex_build_cancel",
        "tex_inspect",
    ):
        spec = get_tool_spec(name)
        assert spec is not None
        assert spec.source == "workspace"
        assert spec.grounding_roles == frozenset({"workspace"})
