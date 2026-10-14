"""Both PDF audit seams must enforce real pdffonts embedding columns."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from domain.documents import audit_pdf, load_profile_catalog
from domain.documents.font_audit import font_diagnostics

HEADER = (
    "name                                 type              encoding         emb sub uni object ID\n"
    "------------------------------------ ----------------- ---------------- --- --- --- ---------\n"
)
UNEMBEDDED = (
    HEADER
    + "Helvetica                            Type 1            WinAnsi          no  no  no       4  0\n"
)
EMBEDDED = (
    HEADER
    + "ABCDEF+DejaVuSerif                    CID TrueType      Identity-H       yes yes yes      8  0\n"
)


def runner():
    spec = importlib.util.spec_from_file_location(
        "document_font_runner", Path(__file__).resolve().parents[1] / "docker/document_runner.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("seam", ["sidecar", "compiler"])
def test_unembedded_real_table_row_blocks_document(seam: str, tmp_path: Path, monkeypatch) -> None:
    if seam == "sidecar":
        profile = load_profile_catalog().get("generic_document")
        result = audit_pdf(
            profile,
            pdfinfo_text="Pages: 1\nPage size: 595 x 842 pts",
            pdffonts_text=UNEMBEDDED,
            qpdf_ok=True,
            extracted_text="Synthetic fixture",
        )
        codes = {item.code for item in result}
    else:
        module = runner()
        monkeypatch.setattr(
            module,
            "output",
            lambda args, *_: (
                UNEMBEDDED if args[0] == "pdffonts" else "Pages: 1\nPage size: 595 x 842 pts"
            ),
        )
        monkeypatch.setattr(
            module,
            "run",
            lambda args, *_: SimpleNamespace(returncode=0, stdout=UNEMBEDDED.encode()),
        )
        _, result = module.pdf_metadata(tmp_path / "fixture.pdf", tmp_path, 15)
        codes = {item["code"] for item in result}
    assert "font_not_embedded" in codes


@pytest.mark.parametrize("fonts", ["", "PRIVATE_FONT_FAILURE", HEADER + "malformed PRIVATE_ROW\n"])
def test_unverifiable_font_report_is_not_success(fonts: str) -> None:
    profile = load_profile_catalog().get("generic_document")
    result = audit_pdf(
        profile,
        pdfinfo_text="Pages: 1\nPage size: 595 x 842 pts",
        pdffonts_text=fonts,
        qpdf_ok=True,
        extracted_text="Synthetic fixture",
    )
    assert any(item.severity == "error" for item in result)
    assert "PRIVATE" not in repr(result)


def test_embedded_fonts_pass_without_font_name_in_diagnostics() -> None:
    profile = load_profile_catalog().get("generic_document")
    result = audit_pdf(
        profile,
        pdfinfo_text="Pages: 1\nPage size: 595 x 842 pts",
        pdffonts_text=EMBEDDED,
        qpdf_ok=True,
        extracted_text="Synthetic fixture",
    )
    assert not result


def test_pdffonts_command_failure_is_not_ignored(tmp_path: Path, monkeypatch) -> None:
    module = runner()
    monkeypatch.setattr(module, "output", lambda *_: "Pages: 1\nPage size: 595 x 842 pts")
    monkeypatch.setattr(
        module,
        "run",
        lambda args, *_: SimpleNamespace(
            returncode=1 if args[0] == "pdffonts" else 0,
            stdout=b"PRIVATE_FONT_BODY",
        ),
    )
    _, result = module.pdf_metadata(tmp_path / "fixture.pdf", tmp_path, 15)
    assert any(item["severity"] == "error" for item in result)
    assert "PRIVATE" not in repr(result)


def test_font_report_is_not_certified_after_silent_truncation(tmp_path: Path, monkeypatch) -> None:
    module = runner()
    monkeypatch.setattr(module, "MAX_LOG_BYTES", len(EMBEDDED.encode()))

    def invoke(args, *_):
        if args[0] == "pdffonts":
            value = EMBEDDED + "UNSEEN FONT Type 1 WinAnsi no no no 99 0\n"
        elif "-f" in args:
            value = "Pages: 1\nPage 1 size: 595 x 842 pts\nPage 1 rot: 0\n"
        else:
            value = "Pages: 1\nPage size: 595 x 842 pts\n"
        return SimpleNamespace(returncode=0, stdout=value.encode())

    monkeypatch.setattr(module, "run", invoke)
    _, result = module.pdf_metadata(tmp_path / "fixture.pdf", tmp_path, 15)
    assert "font_unavailable" in {item["code"] for item in result}
    assert "UNSEEN" not in repr(result)


@pytest.mark.parametrize(
    "kind",
    [
        "Type 1",
        "Type 1C",
        "Type 1C (OT)",
        "CID Type 0",
        "CID Type 0C",
        "CID Type 0C (OT)",
        "TrueType",
        "CID TrueType",
        "CID TrueType (OT)",
    ],
)
def test_known_font_types_parse_with_two_part_object_id(kind: str) -> None:
    report = HEADER + f"PRIVATE FONT NAME {kind} Custom yes no no 123 0\n"
    assert font_diagnostics(report) == ()


def test_type3_in_font_name_does_not_override_real_type_column() -> None:
    assert font_diagnostics(HEADER + "Name Type 3 CID TrueType Identity-H yes yes yes 42 0\n") == ()


def test_type3_is_rejected_even_when_embedded() -> None:
    assert font_diagnostics(HEADER + "Synthetic Type 3 Custom yes no no 12 0\n") == (
        ("type3_font", 1),
    )


def test_header_only_report_is_valid_for_a_fontless_vector_document() -> None:
    assert font_diagnostics(HEADER) == ()


@pytest.mark.parametrize(
    "row",
    [
        "Name Type 1 Custom unknown yes yes 1 0",
        "Name Type 1 Custom yes yes yes PRIVATE_ID 0",
        "Name Unsupported Custom yes yes yes 1 0",
        "Name Type 1 Custom yes yes yes 1",
    ],
)
def test_bad_font_rows_fail_closed_without_raw_fields(row: str) -> None:
    assert font_diagnostics(HEADER + row + "\n") == (("font_unavailable", 1),)


def test_counts_are_bounded_and_do_not_reveal_font_names() -> None:
    result = font_diagnostics(HEADER + "PRIVATE_NAME Type 1 Custom no no no 1 0\n" * 1001)
    assert result == (("font_not_embedded", 999),)
    assert "PRIVATE" not in repr(result)
