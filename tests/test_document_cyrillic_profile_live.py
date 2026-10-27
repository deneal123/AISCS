"""Offline, disposable publisher-profile compilation with Cyrillic semantic text."""

import io
import json
import os
import subprocess
import tarfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from service.domain.documents.intent import deterministic_intent
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock
from service.domain.documents.semantic.rendering import render_document

pytestmark = pytest.mark.skipif(
    os.getenv("GPTHUB_DOCUMENT_LANGUAGE_LIVE") != "1", reason="isolated compiler opt-in"
)


@pytest.mark.parametrize("profile_id", ["ieee_journal", "aaai_conference"])
def test_russian_semantic_text_compiles_with_the_locked_publisher_engine(profile_id):
    root = Path(__file__).resolve().parents[2]
    template = root / "workspace/service/domain/documents/profile_data" / profile_id / "main.tex"
    if not template.exists():
        pytest.skip("profile fixtures belong to the superproject")
    intent = replace(
        deterministic_intent("Подготовь документ"),
        kind="article",
        profile_id=profile_id,
        locale="ru-RU",
        required_sections=(),
        citation_policy="none",
    )
    draft = DocumentDraft(
        1,
        1,
        "Русский черновик",
        (
            DraftBlock(
                "intro", "paragraph", text="Русский текст и English text. Проверка документа."
            ),
        ),
    )
    rendered = render_document(intent, draft, scaffold_source=template.read_text("utf-8"))
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        for name, value in rendered.files.items():
            encoded = value.encode()
            member = tarfile.TarInfo(name)
            member.size = len(encoded)
            archive.addfile(member, io.BytesIO(encoded))
    probe = (
        "import sys,json,pathlib; sys.path.insert(0,'/opt/document-runtime'); import runner; "
        "root=pathlib.Path('/job'); result=runner.run(['latexmk','-pdf',"
        "'-interaction=nonstopmode','-halt-on-error','-file-line-error','-no-shell-escape',"
        "'main.tex'],root,60); log=runner.safe_log(root/'main.log'); "
        "pdf=root/'main.pdf'; meta,checks=runner.pdf_metadata(pdf,root,15) if pdf.is_file() else ({},[]); "
        "text=runner.run(['pdftotext','-enc','UTF-8','main.pdf','-'],root,15).stdout.decode('utf-8','replace') if pdf.is_file() else ''; "
        "print(json.dumps({'exit_code':result.returncode,'unicode_error':'unicode character' in log.lower(),"
        "'russian_text':'Русский текст' in text,'english_text':'English text' in text,"
        "'pages':meta.get('page_count',0),'font_errors':[d['code'] for d in checks if d['severity']=='error']}))"
    )
    name = "gpthub-language-probe-" + uuid4().hex[:12]
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--user=65534:65534",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=512m",
        "--pids-limit=64",
        "--cpus=1",
        "--tmpfs",
        "/job:rw,size=64m,mode=1777",
        "--tmpfs",
        "/tmp:rw,size=128m,mode=1777",
        "--entrypoint",
        "sh",
        os.getenv("GPTHUB_DOCUMENT_RUNTIME_IMAGE", "gpthub-document-runtime:latest"),
        "-c",
        'cd /job && tar xf - && python3 -c "$1"',
        "probe",
        probe,
    ]
    try:
        try:
            result = subprocess.run(
                command, input=payload.getvalue(), capture_output=True, timeout=100, check=False
            )
        except subprocess.TimeoutExpired:
            pytest.fail("isolated_compiler_probe_timeout", pytrace=False)
        assert result.returncode == 0, "isolated_compiler_probe_failed"
        outcome = json.loads(result.stdout)
        assert outcome["exit_code"] == 0, outcome
        assert outcome["pages"] > 0 and outcome["font_errors"] == [], outcome
        assert outcome["russian_text"] and outcome["english_text"], outcome
    finally:
        try:
            cleanup = subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, timeout=15, check=False
            )
            assert cleanup.returncode == 0 or b"No such container" in cleanup.stderr, (
                "isolated_compiler_cleanup_unconfirmed"
            )
        except subprocess.TimeoutExpired:
            pytest.fail("isolated_compiler_cleanup_unconfirmed", pytrace=False)
