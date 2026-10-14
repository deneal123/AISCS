"""Visual audit must receive an exact bounded ordered inventory of PDF pages."""

import importlib.util
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest


def runner():
    spec = importlib.util.spec_from_file_location(
        "document_visual_runner", Path(__file__).resolve().parents[1] / "docker/document_runner.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("report", ["Pages: 201\n", "Pages: 0\n", "PRIVATE_FAILURE"])
def test_invalid_or_over_limit_pdf_never_starts_rasterization(tmp_path, monkeypatch, report):
    module = runner()
    calls = []

    def invoke(args, *_):
        calls.append(args[0])
        if args[0] == "pdftoppm":
            pytest.fail("raster_started_without_bounded_page_preflight")
        return SimpleNamespace(returncode=0, stdout=report.encode())

    monkeypatch.setattr(module, "run", invoke)
    with pytest.raises(ValueError):
        module.visual_bundle(tmp_path / "fixture.pdf", tmp_path, tmp_path, 15)
    assert calls == ["pdfinfo"]
    assert not (tmp_path / "visual-pages").exists()


@pytest.mark.parametrize(
    "names",
    [
        ["page-01.png"],
        ["page-01.png", "page-03.png"],
        ["page-1.png", "page-01.png"],
        ["page-01.png", "page-PRIVATE.png"],
        ["page-00.png", "page-01.png"],
        ["page-01.png", "page-02.png", "page-03.png"],
    ],
)
def test_incomplete_duplicate_or_extra_raster_pages_are_not_attestable(
    tmp_path, monkeypatch, names
):
    module = runner()

    def invoke(args, *_):
        if args[0] == "pdfinfo":
            return SimpleNamespace(returncode=0, stdout=b"Pages: 2\n")
        for name in names:
            (tmp_path / "visual-pages" / name).write_bytes(b"synthetic-image")
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(module, "run", invoke)
    with pytest.raises(ValueError):
        module.visual_bundle(tmp_path / "fixture.pdf", tmp_path, tmp_path, 15)
    assert not (tmp_path / "visual-pages.tar").exists()


def test_page_bundle_is_in_numeric_source_order(tmp_path, monkeypatch):
    module = runner()

    def invoke(args, *_):
        if args[0] == "pdfinfo":
            return SimpleNamespace(returncode=0, stdout=b"Pages: 11\n")
        for page in range(1, 12):
            (tmp_path / "visual-pages" / f"page-{page}.png").write_bytes(f"fixture-{page}".encode())
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(module, "run", invoke)
    bundle, preview = module.visual_bundle(tmp_path / "fixture.pdf", tmp_path, tmp_path, 15)
    with tarfile.open(bundle) as archive:
        values = [archive.extractfile(member).read().decode() for member in archive]
    assert values == [f"fixture-{page}" for page in range(1, 12)]
    assert preview.read_bytes() == b"fixture-1"


def test_final_page_limit_is_deterministic_audit_not_raster_failure(tmp_path, monkeypatch):
    module = runner()
    output = tmp_path / "output"
    (tmp_path / "main.tex").write_text("Synthetic source", encoding="utf-8")
    calls = []

    def invoke(args, *_):
        calls.append(args[0])
        if args[0] == "latexmk":
            (tmp_path / "main.pdf").write_bytes(b"synthetic-pdf")
        if args[0] == "pdftoppm":
            pytest.fail("over_limit_final_rasterized")
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(module, "run", invoke)
    monkeypatch.setattr(module, "pdf_metadata", lambda *_: ({"page_count": 201}, []))
    monkeypatch.setattr(module, "manifest_audit", lambda *_, **__: [])
    monkeypatch.setattr(module, "lint_diagnostics", lambda *_: [])
    monkeypatch.setattr(module, "authoring_manifest_audit", lambda *_: [])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--project",
            str(tmp_path),
            "--entrypoint",
            "main.tex",
            "--engine",
            "xelatex",
            "--output",
            str(output),
            "--publication",
        ],
    )
    assert module.main() == 1
    report = json.loads((output / "report.json").read_text("utf-8"))
    assert report["failure_code"] == "audit_failed"
    assert any(item["code"] == "page_limit" for item in report["diagnostics"])
    assert "pdftoppm" not in calls
    assert not (output / "document.pdf").exists()
