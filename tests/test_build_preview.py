from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from service.core import DocumentSidecar, SidecarError


@pytest.fixture
def preview_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DocumentSidecar:
    sidecar = DocumentSidecar()
    sidecar.root = tmp_path
    document = {"id": "CHECK-001", "entrypoint": "document/specimen.tex"}
    entry = tmp_path / document["entrypoint"]
    entry.parent.mkdir()
    entry.write_text("test source", encoding="utf-8")
    entry.with_suffix(".pdf").write_bytes(b"previous preview")
    monkeypatch.setattr(sidecar, "get_document", lambda document_id: document)
    monkeypatch.setattr(
        sidecar, "validate",
        lambda *, profile, document_id: {"ok": profile == "draft"},
    )
    return sidecar


@pytest.mark.parametrize("outcome", ["success", "first_failure", "second_failure", "timeout"])
def test_preview_waits_for_all_build_passes(
    preview_sidecar: DocumentSidecar, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    calls = 0
    generated = preview_sidecar.root / "build/check-001/specimen.pdf"
    preview = preview_sidecar.root / "document/specimen.pdf"

    def compile_pdf(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        generated.write_bytes(f"PDF from pass {calls}".encode())
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 120)
        failed = outcome == "first_failure" or (outcome == "second_failure" and calls == 2)
        return subprocess.CompletedProcess(command, int(failed), stdout="", stderr="")

    monkeypatch.setattr("service.core.subprocess.run", compile_pdf)
    result = preview_sidecar.build("CHECK-001")
    if outcome == "success":
        assert result["ok"] is True
        assert calls == 2
        assert preview.read_bytes() == generated.read_bytes() == b"PDF from pass 2"
    else:
        assert result["ok"] is False
        assert preview.read_bytes() == b"previous preview"


@pytest.mark.parametrize("mode", ["dry_run", "release"])
def test_preview_is_unchanged_when_build_is_not_authorized(
    preview_sidecar: DocumentSidecar, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    def unexpected_compile(*args: object, **kwargs: object) -> None:
        pytest.fail("compiler must not run")

    monkeypatch.setattr("service.core.subprocess.run", unexpected_compile)
    result = preview_sidecar.build(
        "CHECK-001", profile="release" if mode == "release" else "draft",
        apply=mode != "dry_run",
    )
    assert result["applied"] is False
    assert result["ok"] is (mode == "dry_run")
    assert (preview_sidecar.root / "document/specimen.pdf").read_bytes() == b"previous preview"
    assert not (preview_sidecar.root / "build").exists()


def test_preview_survives_failed_atomic_replace(
    preview_sidecar: DocumentSidecar, monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = preview_sidecar.root / "build/check-001/specimen.pdf"

    def compile_pdf(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        generated.write_bytes(b"new PDF")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def failed_replace(*args: object) -> None:
        raise PermissionError("preview is locked")

    monkeypatch.setattr("service.core.subprocess.run", compile_pdf)
    monkeypatch.setattr("service.core.os.replace", failed_replace)
    with pytest.raises(SidecarError, match="cannot update PDF preview"):
        preview_sidecar.build("CHECK-001")
    assert (preview_sidecar.root / "document/specimen.pdf").read_bytes() == b"previous preview"
    assert not list((preview_sidecar.root / "document").glob(".specimen.pdf.*.tmp"))

def test_biber_can_resolve_bibliography_in_the_source_directory(
    preview_sidecar: DocumentSidecar, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview_sidecar.config["uses_biber"] = True
    monkeypatch.setattr(preview_sidecar, "validate", lambda **kwargs: {"ok": True})
    source_dir = preview_sidecar.root / "document"
    bibliography = source_dir / "backmatter/references.bib"
    bibliography.parent.mkdir()
    bibliography.write_text("@article{example, title={Example}}", encoding="utf-8")
    build_dir = preview_sidecar.root / "build/check-001"

    def compile_pdf(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = Path(str(kwargs["cwd"]))
        if command[0] == "biber":
            assert (cwd / "backmatter/references.bib").is_file()
            assert Path(command[-1]).with_suffix(".bcf").is_file()
            output_dir = Path(next(
                arg.split("=", 1)[1] for arg in command if arg.startswith("--output-directory=")
            ))
            (output_dir / "specimen.bbl").write_text("bibliography", encoding="utf-8")
        else:
            (build_dir / "specimen.bcf").write_text("control file", encoding="utf-8")
            (build_dir / "specimen.pdf").write_bytes(b"compiled PDF")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("service.core.subprocess.run", compile_pdf)
    result = preview_sidecar.build("CHECK-001", profile="release")
    assert result["ok"] is True
    assert len(result["commands"]) == 4
    assert (build_dir / "specimen.bbl").is_file()
    assert (source_dir / "specimen.pdf").read_bytes() == b"compiled PDF"
