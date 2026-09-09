from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from application.documents.projects import scaffold_archive
from domain.documents import ProfileConfigurationError, load_profile_catalog


def test_builtin_document_profiles_are_complete_and_stable() -> None:
    catalog = load_profile_catalog()

    assert catalog.version == "s34.v1"
    assert len(catalog.digest) == 64
    assert tuple(catalog.profiles) == (
        "aaai_conference",
        "beamer_16_9",
        "generic_article",
        "generic_document",
        "generic_report",
        "ieee_journal",
        "legal_ru",
    )
    assert catalog.get("beamer_16_9").orientation == "landscape"
    assert catalog.get("generic_article").bibliography_required is True
    assert catalog.get("legal_ru").kind == "legal"


def test_scaffold_contains_contract_sources_and_no_registry_manifest() -> None:
    profile = load_profile_catalog().get("generic_article")
    assert profile is not None

    payload = scaffold_archive(profile, mode="submission", locale="ru-RU")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        names = set(archive.getnames())
        manifest = archive.extractfile("document.toml")
        assert manifest is not None
        text = manifest.read().decode()

    assert {"document.toml", "main.tex", "gpthub-core.sty", ".gitignore"} <= names
    assert "bibliography/references.bib" in names
    assert "profile.toml" not in names
    assert 'profile_id = "generic_article"' in text
    assert 'mode = "submission"' in text


def test_profile_catalog_rejects_unsafe_entrypoint(tmp_path: Path) -> None:
    profile = tmp_path / "unsafe_profile"
    profile.mkdir()
    (profile / "profile.toml").write_text(
        "\n".join(
            (
                'profile_id = "unsafe_profile"',
                "version = 1",
                'kind = "report"',
                'engine = "xelatex"',
                'entrypoint = "../main.tex"',
                'source_export = "forbidden"',
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProfileConfigurationError, match="entrypoint_invalid"):
        load_profile_catalog(tmp_path)
