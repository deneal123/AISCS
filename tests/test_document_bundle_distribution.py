"""Чистая поставка содержит рабочие шаблоны без данных dev-стенда."""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
from application.documents.bundle_check import verify_document_bundle
from domain.documents import ProfileConfigurationError

ROOT = Path(__file__).parents[1]
ASSETS = Path("service/domain/documents/profile_data")


def test_packaged_templates_form_complete_scaffolds():
    assert verify_document_bundle() == 7


def test_git_export_alone_contains_all_builtin_templates(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("Проверка чистого экспорта требует Git")
    exported = subprocess.run(
        ["git", "archive", "HEAD", ASSETS.as_posix()],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(exported), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            relative = Path(member.name)
            assert not relative.is_absolute() and ".." not in relative.parts
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            assert source is not None
            target.write_bytes(source.read())
    assert verify_document_bundle(tmp_path / ASSETS) == 7


def test_missing_shared_style_cannot_pass_image_bundle_check(tmp_path):
    copied = tmp_path / "profiles"
    shutil.copytree(ROOT / ASSETS, copied)
    (copied / "_shared/gpthub-core.sty").unlink()
    with pytest.raises(ProfileConfigurationError, match="profile_bundle_incomplete"):
        verify_document_bundle(copied)


def test_missing_profile_cannot_pass_image_bundle_check(tmp_path):
    copied = tmp_path / "profiles"
    shutil.copytree(ROOT / ASSETS, copied)
    # Проверяем неполную поставку, не трогая отслеживаемые файлы репозитория.
    shutil.rmtree(copied / "beamer_16_9")
    with pytest.raises(ProfileConfigurationError, match="profile_bundle_incomplete"):
        verify_document_bundle(copied)
