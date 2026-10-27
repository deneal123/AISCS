"""Opt-in semantic renderer -> real trusted profile compiler corpus, without LLM."""

import hashlib
import importlib.util
import io
import json
import os
import re
import struct
import subprocess
import tarfile
import uuid
import zlib
from pathlib import Path

import pytest

from service.domain.documents import CitationRegistry, DocumentDraft, DocumentIntent, DraftBlock
from service.domain.documents.semantic.rendering import render_document
from service.domain.subagents.research import ResearchArtifact, SourceRecord

ROOT = Path(__file__).resolve().parents[2]
PROFILE_ROOT = ROOT / "workspace/service/domain/documents/profile_data"
PROFILES = sorted(path.name for path in PROFILE_ROOT.iterdir() if not path.name.startswith("_"))
pytestmark = pytest.mark.skipif(
    os.environ.get("GPTHUB_DOCUMENT_PROFILE_LIVE") != "1",
    reason="real semantic document profile corpus is opt-in",
)


def _png() -> bytes:
    """Small procedural fixture, not user content or an external image asset."""

    def chunk(kind: bytes, value: bytes) -> bytes:
        return (
            struct.pack(">I", len(value))
            + kind
            + value
            + struct.pack(">I", zlib.crc32(kind + value))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + bytes([40, 100, 180]) * 16) * 16))
        + chunk(b"IEND", b"")
    )


def _source(profile_id: str) -> tuple[bytes, str]:
    spec = importlib.util.spec_from_file_location(
        "document_smoke", ROOT / "scripts/smoke_document_runtime.py"
    )
    assert spec and spec.loader
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    baseline, profile = smoke._source_archive(profile_id, publication=False)
    assert profile["engine"] in {"xelatex", "lualatex", "pdflatex"}
    with tarfile.open(fileobj=io.BytesIO(baseline)) as archive:
        files = {item.name: archive.extractfile(item).read() for item in archive if item.isfile()}
    article = profile["kind"] == "article"
    citation = CitationRegistry(
        ResearchArtifact(
            1,
            (
                SourceRecord(
                    1,
                    "https://example.org/synthetic-corpus",
                    "Synthetic Corpus Reference",
                    "Fixture only",
                    "text",
                    hashlib.sha256(b"synthetic-corpus").hexdigest(),
                    ("Fixture Author",),
                    2024,
                ),
            ),
        )
    )
    intent = DocumentIntent(
        1,
        "Synthetic document corpus",
        profile["kind"],
        profile_id,
        profile["locale"],
        "draft",
        "Corpus Document",
        "acceptance",
        "standard",
        tuple(profile.get("required_sections", ())),
        "required" if article else "none",
        "balanced",
        (),
        (),
    )
    if profile["kind"] == "presentation":
        blocks = (
            DraftBlock(
                "slide_first",
                "slide",
                title="Corpus First",
                items=("CorpusStart", "Synthetic fixture"),
            ),
            DraftBlock(
                "slide_middle",
                "slide",
                title="Corpus Middle",
                columns=("Item", "Value"),
                rows=(("A", "1"), ("B", "2")),
            ),
            DraftBlock(
                "slide_last",
                "slide",
                title="Corpus Last",
                text="CorpusEnd",
                asset_path="figures/fixture.png",
            ),
        )
    else:
        blocks = (
            DraftBlock(
                "corpus_start",
                "paragraph",
                text="CorpusStart. Synthetic fixture, not a real publication.",
            ),
            DraftBlock(
                "corpus_table",
                "table",
                title="Corpus Table",
                columns=("Item", "Value"),
                rows=(("A", "1"), ("B", "2")),
            ),
            DraftBlock("corpus_equation", "equation", text=r"\text{Value} = \sum_{i=1}^{3}i = 6"),
            DraftBlock(
                "corpus_figure", "figure", title="Corpus Figure", asset_path="figures/fixture.png"
            ),
            *(
                (
                    DraftBlock(
                        "corpus_citation",
                        "citation",
                        text="Registered synthetic evidence",
                        source_id=1,
                    ),
                )
                if article
                else ()
            ),
            *(
                (
                    DraftBlock(
                        "corpus_signature",
                        "signature",
                        items=("Fixture Party One", "Fixture Party Two"),
                    ),
                )
                if profile["kind"] == "legal"
                else ()
            ),
            DraftBlock("corpus_end", "paragraph", text="CorpusEnd. Synthetic fixture complete."),
        )
    rendered = render_document(
        intent,
        DocumentDraft(1, 1, intent.title, blocks),
        scaffold_source=files["main.tex"].decode(),
        citations=citation,
        bibliography=citation.bibliography() if article else "",
    )
    files.update({name: value.encode() for name, value in rendered.files.items()})
    files["figures/fixture.png"] = _png()
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w") as archive:
        for name, content in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
    return result.getvalue(), profile["engine"]


def _compiled_report(payload: bytes, engine: str) -> tuple[dict, str]:
    name = "gpthub-profile-corpus-" + uuid.uuid4().hex[:12]
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network=none",
        "--memory=1536m",
        "--pids-limit=384",
        "--cpus=2",
        "--user=65534:65534",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--tmpfs",
        "/job:rw,size=64m,mode=1777",
        "--tmpfs",
        "/output:rw,size=128m,mode=1777",
        "--tmpfs",
        "/tmp:rw,size=256m,mode=1777",
        "--entrypoint",
        "sh",
        "gpthub-document-runtime:latest",
        "-c",
        "cd /job && tar xf - && python3 /opt/document-runtime/runner.py "
        "--project /job --entrypoint main.tex --engine " + engine + " --timeout 90 "
        "> /tmp/runner.log 2>&1; cat /output/report.json; "
        "printf '\\nCORPUS_TEXT_BEGIN\\n'; "
        "if test -f /output/document.pdf; then pdftotext -raw /output/document.pdf -; fi",
    ]
    try:
        result = subprocess.run(command, input=payload, capture_output=True, timeout=130)
        report_text, _, text = result.stdout.decode("utf-8", "replace").partition(
            "\nCORPUS_TEXT_BEGIN\n"
        )
        try:
            report = json.loads(report_text)
        except ValueError:
            pytest.fail("profile_report_missing_or_invalid")
        return report, text
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)


@pytest.mark.parametrize("profile_id", PROFILES)
def test_semantic_profile_compiles_complete_text_and_registered_sources(profile_id: str) -> None:
    report, text = _compiled_report(*_source(profile_id))
    codes = {item.get("code") for item in report.get("diagnostics", [])}
    bounded_codes = codes & {
        "compile_failed",
        "undefined_control_sequence",
        "unresolved_placeholder",
        "overfull_box",
        "audit_failed",
        "authoring_invalid",
        "required_section",
    }
    assert report.get("status") == "ready", "semantic_profile_failed:" + ",".join(
        sorted(bounded_codes)
    )
    assert not codes & {
        "unresolved_placeholder",
        "citation_missing",
        "bibliography_missing",
        "overfull_box",
    }, "semantic_content_not_preserved"
    # Raw content-stream extraction avoids interleaving two adjacent columns.
    # Restore tokens split at typeset hyphenation boundaries; page composition
    # remains a separate visual acceptance, not a claim made by this text check.
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)
    assert "CorpusStart" in text and "CorpusEnd" in text, "semantic_content_missing"
    if profile_id in {"generic_article", "ieee_journal", "aaai_conference"}:
        assert "synthetic corpus reference" in " ".join(text.split()).casefold(), (
            "registered_bibliography_missing"
        )
    if profile_id == "beamer_16_9":
        assert report["page_width_pt"] > report["page_height_pt"], "presentation_not_landscape"
    assert report["page_count"] >= 1


def test_retained_legacy_title_causes_a_real_false_placeholder_diagnostic() -> None:
    payload, engine = _source("legal_ru")
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        files = {item.name: archive.extractfile(item).read() for item in archive if item.isfile()}
    new_title = b"\\title{Corpus Document}"
    old_title = "\\title{\\DocumentPlaceholder{Название документа}}\n".encode()
    assert new_title in files["main.tex"]
    files["main.tex"] = files["main.tex"].replace(new_title, old_title + new_title, 1)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, value in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(value)
            archive.addfile(item, io.BytesIO(value))
    report, _ = _compiled_report(stream.getvalue(), engine)
    assert report["status"] == "ready"
    assert any(
        item.get("code") == "unresolved_placeholder" for item in report.get("diagnostics", [])
    ), "legacy_title_did_not_reproduce_the_placeholder_false_positive"
