from __future__ import annotations

from domain.documents import audit_log, audit_pdf, load_profile_catalog, pdf_facts


def test_log_audit_returns_only_bounded_diagnostics() -> None:
    marker = "PRIVATE-SOURCE-MARKER"
    result = audit_log(
        f"main.tex:27: {marker}\nFatal error\nOverfull \\hbox\nThere were undefined references"
    )

    assert {item.code for item in result} == {
        "compile_error",
        "overfull_box",
        "undefined_reference",
    }
    assert marker not in repr(result)
    assert next(item for item in result if item.code == "compile_error").line == 27


def test_pdf_audit_checks_geometry_fonts_bibliography_and_sections() -> None:
    catalog = load_profile_catalog()
    profile = catalog.get("generic_article")
    assert profile is not None

    result = audit_pdf(
        profile,
        pdfinfo_text="Pages: 2\nPage size: 792 x 612 pts",
        pdffonts_text="Broken Type 3 font",
        qpdf_ok=True,
        extracted_text="Draft without required blocks {{LEGAL_NAME}}",
    )
    codes = {item.code for item in result}

    assert "orientation_mismatch" in codes
    assert "type3_font" in codes
    assert "bibliography_missing" in codes
    assert "required_section_missing" in codes
    assert "placeholder_unresolved" in codes


def test_pdf_facts_are_safe_for_malformed_output() -> None:
    assert pdf_facts("not provider output") == (0, 0.0, 0.0)
