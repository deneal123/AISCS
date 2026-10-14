"""Every output page, not only the first, must satisfy locked geometry."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from document_page_audit import geometry_diagnostics, page_count, page_inventory

HEADER = "name type encoding emb sub uni object ID\n----------------------------------------\n"
SUMMARY = "Pages: 2\nPage size: 595.28 x 841.89 pts (A4)\nPage rot: 0\n"


def runner():
    spec = importlib.util.spec_from_file_location(
        "document_page_runner", Path(__file__).resolve().parents[1] / "docker/document_runner.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def project(tmp_path: Path) -> Path:
    (tmp_path / "document.toml").write_text(
        'entrypoint="main.tex"\ndocumentclass="article"\npaper="a4"\n'
        'orientation="portrait"\nanonymize=false\nbibliography_required=false\n',
        encoding="utf-8",
    )
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Synthetic fixture\end{document}",
        encoding="utf-8",
    )
    return tmp_path


def audit(tmp_path, monkeypatch, detail, *, info_exit=0):
    module = runner()

    def invoke(args, *_):
        value = HEADER if args[0] == "pdffonts" else detail if "-f" in args else SUMMARY
        return SimpleNamespace(
            returncode=info_exit if args[0] == "pdfinfo" else 0,
            stdout=value.encode(),
        )

    monkeypatch.setattr(module, "run", invoke)
    monkeypatch.setattr(module, "output", lambda args, *_: invoke(args).stdout.decode())
    metadata, diagnostics = module.pdf_metadata(tmp_path / "fixture.pdf", tmp_path, 15)
    return [
        *diagnostics,
        *module.manifest_audit(project(tmp_path), metadata, publication=False),
    ]


@pytest.mark.parametrize(
    ("second", "code"),
    [
        ("Page 2 size: 612 x 792 pts\nPage 2 rot: 0\n", "page_geometry"),
        ("Page 2 size: 595.28 x 841.89 pts\nPage 2 rot: 90\n", "page_orientation"),
    ],
)
def test_second_page_cannot_bypass_locked_profile(tmp_path, monkeypatch, second, code):
    detail = SUMMARY + "Page 1 size: 595.28 x 841.89 pts\nPage 1 rot: 0\n" + second
    result = audit(tmp_path, monkeypatch, detail)
    assert code in {item["code"] for item in result}


@pytest.mark.parametrize(
    "detail",
    [
        SUMMARY,
        SUMMARY + "Page 1 size: 595.28 x 841.89 pts\nPage 1 rot: 0\n",
        SUMMARY
        + "Page 1 size: 595.28 x 841.89 pts\nPage 1 rot: 0\n"
        + "Page 1 size: 595.28 x 841.89 pts\nPage 1 rot: 0\n",
    ],
)
def test_incomplete_or_duplicate_page_inventory_fails_closed(tmp_path, monkeypatch, detail):
    result = audit(tmp_path, monkeypatch, detail)
    assert "pdf_invalid" in {item["code"] for item in result}


def test_failed_pdfinfo_cannot_certify_output(tmp_path, monkeypatch):
    detail = SUMMARY + "PRIVATE_PROVIDER_BODY"
    result = audit(tmp_path, monkeypatch, detail, info_exit=1)
    assert "pdf_invalid" in {item["code"] for item in result}
    assert "PRIVATE" not in repr(result)


def test_all_matching_pages_are_accepted(tmp_path, monkeypatch):
    detail = SUMMARY + "".join(
        f"Page {page} size: 595.28 x 841.89 pts\nPage {page} rot: 0\n" for page in (1, 2)
    )
    assert audit(tmp_path, monkeypatch, detail) == []


@pytest.mark.parametrize(
    "report",
    ["", "Pages: 0", "Pages: 10001", "Pages: 1\nPages: 1", "Pages: ١", "Pages: " + "9" * 80],
)
def test_invalid_page_count_is_bounded(report):
    with pytest.raises(ValueError, match="^pdf_invalid$"):
        page_count(report)


@pytest.mark.parametrize(
    ("size", "rotation"),
    [
        ("0 x 842", "0"),
        ("595 x 0", "0"),
        ("-595 x 842", "0"),
        ("nan x 842", "0"),
        ("100001 x 842", "0"),
        ("5..95 x 842", "0"),
        ("595 x 842", "360"),
        ("595 x 842", "45"),
    ],
)
def test_invalid_geometry_or_rotation_is_bounded(size, rotation):
    text = f"Pages: 1\nPage 1 size: {size} pts\nPage 1 rot: {rotation}\n"
    with pytest.raises(ValueError):
        page_inventory(text, 1)


def test_rotation_is_used_for_visible_orientation():
    assert geometry_diagnostics(((595.3, 841.9, 180),), "a4", "portrait") == ()
    assert geometry_diagnostics(((595.3, 841.9, 270),), "a4", "portrait") == (
        ("page_orientation", 1),
    )
    assert geometry_diagnostics(((841.9, 595.3, 0),), "a4", "landscape") == ()
    assert geometry_diagnostics(((595.3, 841.9, 90),), "a4", "landscape") == ()


def test_geometry_diagnostics_are_aggregate_only():
    assert geometry_diagnostics(((612.0, 792.0, 90),) * 1001, "a4", "portrait") == (
        ("page_geometry", 999),
        ("page_orientation", 999),
    )


def test_report_limits_and_duplicate_rotations_are_not_accepted():
    with pytest.raises(ValueError, match="^pdf_invalid$"):
        page_inventory("PRIVATE" * 600_000, 1)
    with pytest.raises(ValueError, match="^pdf_invalid$"):
        page_inventory(
            "Pages: 2\nPage 1 size: 595 x 842 pts\nPage 2 size: 595 x 842 pts\n"
            "Page 1 rot: 0\nPage 1 rot: 0\n",
            2,
        )
