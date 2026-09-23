from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from mcp import Client

from service.core import DocumentSidecar, SidecarError, sha256
from service.mcp_server import create_server

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("template", ["article", "abstract", "supplement"])
def test_publication_template_builds_after_independent_copy(
    tmp_path: Path, template: str
) -> None:
    if shutil.which("xelatex") is None:
        pytest.skip("xelatex is unavailable")
    portable = tmp_path / f"publication-{template}"
    shutil.copytree(ROOT / "documents" / "_templates" / template, portable)
    output = portable / "build"
    output.mkdir()
    result = subprocess.run(
        [
            "xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={output}",
            "main.tex",
        ],
        cwd=portable,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:]
    assert (output / "main.pdf").is_file()


def test_integrity_and_release_gate() -> None:
    sidecar = DocumentSidecar(ROOT)
    draft = sidecar.validate(profile="draft")
    assert draft["ok"], draft["errors"]
    release = sidecar.validate(profile="release")
    assert release["ok"] is False
    assert any("release approvals" in item or "placeholders" in item for item in release["errors"])


def test_registry_and_research_snapshot_are_available() -> None:
    sidecar = DocumentSidecar(ROOT)
    assert (ROOT / "data" / "document-registry.schema.json").is_file()
    assert sidecar.list_documents()["total"] >= 1
    snapshot = sidecar.get_research_snapshot()
    assert snapshot["available"] is True
    assert snapshot["selected_refs"]


def test_submitted_publication_contract_and_new_dry_run() -> None:
    sidecar = DocumentSidecar(ROOT)
    submitted = sidecar.get_document("PUB-001")
    assert submitted is not None
    assert submitted["title"] == (
        "Методы оценки болевого состояния по биомедицинским данным: целевые переменные, "
        "доступные наборы данных и требования к валидации"
    )
    assert submitted["status"] == "submitted"
    assert submitted["immutable"] is True
    planned = sidecar.new_publication("PUB-999", "dry-run", "Черновик", "paper", "ru", apply=False)
    assert planned["applied"] is False
    assert planned["document"]["source_dir"] == "documents/PUB-999"
    assert not (ROOT / "documents" / "PUB-999").exists()


def test_build_dry_run_does_not_write() -> None:
    sidecar = DocumentSidecar(ROOT)
    mutable = next(item for item in sidecar.list_documents()["items"] if not item["immutable"])
    result = sidecar.build(mutable["id"], profile="draft", apply=False)
    assert result["ok"] is True
    assert result["applied"] is False
    assert all(
        not ({"build", "archive", "examples", "releases", ".venv"} & set(relative.parts))
        for _, relative in sidecar._source_files(mutable)
    )


def test_path_traversal_and_optimistic_write(tmp_path: Path) -> None:
    destination = tmp_path / "sidecar"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".venv", ".pytest_cache", ".ruff_cache", "build", "archive", "examples"
        ),
    )
    sidecar = DocumentSidecar(destination)
    with pytest.raises(SidecarError):
        sidecar.save_section("../escape.tex", "bad", None, apply=True)
    mutable = next(item for item in sidecar.list_documents()["items"] if not item["immutable"])
    entry = destination / mutable["entrypoint"]
    with pytest.raises(SidecarError, match="expected_sha256"):
        sidecar.save_section(str(entry.relative_to(destination)), "changed", None, apply=True)
    with pytest.raises(SidecarError, match="changed since"):
        sidecar.save_section(str(entry.relative_to(destination)), "changed", "0" * 64, apply=True)
    result = sidecar.save_section(
        str(entry.relative_to(destination)),
        entry.read_text(encoding="utf-8"),
        sha256(entry),
        apply=False,
    )
    assert result["applied"] is False


def test_imported_research_item_hash_is_enforced(tmp_path: Path) -> None:
    destination = tmp_path / "sidecar"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".venv", ".pytest_cache", ".ruff_cache", "build", "archive", "examples"
        ),
    )
    snapshot_path = destination / "data" / "research-snapshot" / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["sources"][0]["название"] = "tampered"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    checked = DocumentSidecar(destination).validate()
    assert checked["ok"] is False
    assert any("research snapshot item hash mismatch" in item for item in checked["errors"])


def test_release_manifest_hash_is_enforced(tmp_path: Path) -> None:
    destination = tmp_path / "sidecar"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".venv", ".pytest_cache", ".ruff_cache", "build", "archive", "examples"
        ),
    )
    release_dir = destination / "releases" / "fixture"
    release_dir.mkdir(parents=True)
    artifact = release_dir / "artifact.pdf"
    artifact.write_bytes(b"fixture")
    (release_dir / "manifest.json").write_text(
        json.dumps(
            {"files": [{"name": artifact.name, "sha256": sha256(artifact)}]},
            indent=2,
        ),
        encoding="utf-8",
    )
    assert DocumentSidecar(destination).validate()["ok"] is True
    artifact.write_bytes(b"tampered")
    checked = DocumentSidecar(destination).validate()
    assert checked["ok"] is False
    assert any("release hash mismatch" in item for item in checked["errors"])


def test_immutable_document_is_protected_when_present(tmp_path: Path) -> None:
    sidecar = DocumentSidecar(ROOT)
    immutable = next(
        (item for item in sidecar.list_documents()["items"] if item["immutable"]), None
    )
    if immutable is None:
        pytest.skip("sidecar has no immutable document")
    source_dir = ROOT / immutable["source_dir"]
    path = next(
        item
        for item in source_dir.rglob("*")
        if item.suffix.lower() in {".tex", ".bib", ".md", ".json"}
    )
    with pytest.raises(SidecarError, match="immutable"):
        sidecar.save_section(
            str(path.relative_to(ROOT)),
            path.read_text(encoding="utf-8", errors="replace"),
            sha256(path),
            apply=True,
        )


def test_mcp_protocol_and_resources() -> None:
    async def exercise() -> None:
        async with Client(create_server(ROOT)) as client:
            tools = await client.list_tools()
            assert {
                "status",
                "list_documents",
                "get_document_context",
                "validate",
                "get_research_snapshot",
                "save_section",
                "build",
                "snapshot",
                "import_research_snapshot",
                "release",
            } == {item.name for item in tools.tools}
            resources = await client.list_resources()
            assert {
                "document://guide",
                "document://todo",
                "document://registry",
                "document://outline",
                "document://research-snapshot",
            } <= {str(item.uri) for item in resources.resources}
            templates = await client.list_resource_templates()
            assert {
                "document://document/{document_id}",
                "document://validation-report/{document_id}",
            } <= {str(item.uri_template) for item in templates.resource_templates}
            guide = await client.read_resource("document://guide")
            assert guide.contents
            archive_count = len(list((ROOT / "archive").glob("*/manifest.json")))
            dry_snapshot = await client.call_tool("snapshot", {"label": "mcp-dry-run"})
            assert dry_snapshot.structured_content["applied"] is False
            assert archive_count == len(list((ROOT / "archive").glob("*/manifest.json")))
            result = await client.call_tool("status", {})
            assert result.is_error is not True
            assert result.structured_content["integrity"]["ok"] is True

    asyncio.run(exercise())
