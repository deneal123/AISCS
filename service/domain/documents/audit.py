"""Parse compiler output into bounded diagnostics without exposing raw logs."""

from __future__ import annotations

import re

from .contracts import DocumentDiagnostic, DocumentProfile
from .font_audit import font_diagnostics

_FILE_LINE = re.compile(r"(?:^|\n)([^\n:]{1,180}\.tex):(\d+):")
_PAGES = re.compile(r"Pages:\s*(\d+)", re.IGNORECASE)
_PAGE_SIZE = re.compile(r"Page size:\s*([\d.]+)\s+x\s+([\d.]+)\s+pts", re.IGNORECASE)


def _count(text: str, *needles: str) -> int:
    lowered = text.lower()
    return sum(lowered.count(needle.lower()) for needle in needles)


def audit_log(log_text: str) -> tuple[DocumentDiagnostic, ...]:
    """Map known TeX conditions to stable codes; never return log fragments."""
    raw = str(log_text or "")
    diagnostics: list[DocumentDiagnostic] = []
    checks = (
        ("error", "undefined_reference", ("reference `", "undefined references")),
        ("error", "undefined_citation", ("citation `", "undefined citations")),
        ("error", "multiply_defined", ("multiply defined",)),
        ("warning", "overfull_box", ("overfull \\hbox", "overfull \\vbox")),
        ("warning", "underfull_box", ("underfull \\hbox", "underfull \\vbox")),
        ("error", "missing_file", ("file `", "not found")),
    )
    for severity, code, needles in checks:
        count = _count(raw, *needles)
        if count:
            diagnostics.append(DocumentDiagnostic(severity, code, count=count))
    if "fatal error" in raw.lower() or "emergency stop" in raw.lower():
        match = _FILE_LINE.search(raw)
        diagnostics.append(
            DocumentDiagnostic(
                "error",
                "compile_error",
                relative_path=(
                    match.group(1).replace("\\", "/").rsplit("/", 1)[-1] if match else ""
                ),
                line=(int(match.group(2)) if match else None),
            )
        )
    return tuple(diagnostics)


def pdf_facts(pdfinfo_text: str) -> tuple[int, float, float]:
    pages = _PAGES.search(str(pdfinfo_text or ""))
    size = _PAGE_SIZE.search(str(pdfinfo_text or ""))
    return (
        int(pages.group(1)) if pages else 0,
        float(size.group(1)) if size else 0.0,
        float(size.group(2)) if size else 0.0,
    )


def audit_pdf(
    profile: DocumentProfile,
    *,
    pdfinfo_text: str,
    pdffonts_text: str,
    qpdf_ok: bool,
    extracted_text: str,
) -> tuple[DocumentDiagnostic, ...]:
    diagnostics: list[DocumentDiagnostic] = []
    pages, width, height = pdf_facts(pdfinfo_text)
    if not qpdf_ok or pages < 1:
        diagnostics.append(DocumentDiagnostic("error", "pdf_invalid"))
    if profile.max_pages and pages > profile.max_pages:
        diagnostics.append(DocumentDiagnostic("error", "page_limit", count=pages))
    if profile.orientation == "landscape" and width and height and width <= height:
        diagnostics.append(DocumentDiagnostic("error", "orientation_mismatch"))
    if profile.orientation == "portrait" and width and height and width >= height:
        diagnostics.append(DocumentDiagnostic("error", "orientation_mismatch"))
    diagnostics.extend(
        DocumentDiagnostic("error", code, count=count)
        for code, count in font_diagnostics(pdffonts_text)
    )
    if profile.bibliography_required and not re.search(
        r"references|bibliography|литератур", str(extracted_text or ""), re.IGNORECASE
    ):
        diagnostics.append(DocumentDiagnostic("error", "bibliography_missing"))
    for section in profile.required_sections:
        if section.lower() not in str(extracted_text or "").lower():
            diagnostics.append(DocumentDiagnostic("error", "required_section_missing"))
    if "{{" in extracted_text or "}}" in extracted_text:
        diagnostics.append(DocumentDiagnostic("error", "placeholder_unresolved"))
    return tuple(diagnostics)


def has_blocking_diagnostics(items: tuple[DocumentDiagnostic, ...]) -> bool:
    return any(item.severity == "error" for item in items)
