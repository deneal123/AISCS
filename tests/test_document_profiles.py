from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path

import pytest
from application.documents.projects import scaffold_archive
from domain.documents import ProfileConfigurationError, load_profile_catalog


def test_builtin_document_profiles_are_complete_and_stable() -> None:
    catalog = load_profile_catalog()

    assert catalog.version == "s35.v1"
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


def test_shared_renderer_module_is_part_of_every_profile_digest(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "service" / "domain" / "documents" / "profile_data"
    root = tmp_path / "profiles"
    shutil.copytree(source, root)
    before = load_profile_catalog(root)
    shared = root / "_shared" / "gpthub-core.sty"
    shared.write_text(shared.read_text(encoding="utf-8") + "\n% digest change\n", encoding="utf-8")
    after = load_profile_catalog(root)

    assert before.digest != after.digest
    assert all(
        before.profiles[profile_id].digest != after.profiles[profile_id].digest
        for profile_id in before.profiles
    )


def test_shared_callout_is_a_balanced_command() -> None:
    root = Path(__file__).parents[1] / "service" / "domain" / "documents" / "profile_data"
    source = (root / "_shared" / "gpthub-core.sty").read_text(encoding="utf-8")

    assert r"\newcommand{\DocumentCallout}[1]" in source
    assert r"\newenvironment{DocumentCallout}" not in source


@pytest.mark.parametrize(
    ("field", "literal"),
    [
        ("version", "true"),
        ("version", "1.5"),
        ("version", '"2"'),
        ("max_pages", "true"),
        ("max_pages", "0"),
        ("max_pages", "-1"),
        ("max_pages", "8.5"),
        ("max_pages", '"8"'),
        ("bibliography_required", '"false"'),
        ("bibliography_required", "0"),
        ("bibliography_required", "1"),
        ("anonymize_supported", '"false"'),
        ("anonymize_supported", "0"),
        ("anonymize_supported", "1"),
    ],
)
def test_profile_manifest_does_not_coerce_policy_fields(tmp_path, field, literal):
    source = Path(__file__).parents[1] / "service/domain/documents/profile_data/generic_report"
    target = tmp_path / "generic_report"
    shutil.copytree(source, target)
    manifest = target / "profile.toml"
    rows = [
        row
        for row in manifest.read_text(encoding="utf-8").splitlines()
        if not row.startswith(f"{field} =")
    ]
    manifest.write_text("\n".join([*rows, f"{field} = {literal}", ""]), encoding="utf-8")

    with pytest.raises(ProfileConfigurationError, match="^profile_invalid$"):
        load_profile_catalog(tmp_path)


@pytest.mark.parametrize("entrypoint", ["nested/../../outside.tex", "nested/../main.tex"])
def test_profile_rejects_embedded_parent_segments(tmp_path, entrypoint):
    source = Path(__file__).parents[1] / "service/domain/documents/profile_data/generic_report"
    target = tmp_path / "generic_report"
    shutil.copytree(source, target)
    (target / "nested").mkdir()
    (tmp_path / "outside.tex").write_text("private-fixture", encoding="utf-8")
    manifest = target / "profile.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            'entrypoint = "main.tex"', f'entrypoint = "{entrypoint}"'
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProfileConfigurationError, match="^entrypoint_invalid$"):
        load_profile_catalog(tmp_path)


@pytest.mark.parametrize("location", ["main.tex", "asset.sty", "shared"])
def test_profile_catalog_rejects_symlinked_template_files(tmp_path, location):
    source = Path(__file__).parents[1] / "service/domain/documents/profile_data/generic_report"
    target = tmp_path / "generic_report"
    shutil.copytree(source, target)
    external = tmp_path / "external.sty"
    external.write_text("private-template-marker", encoding="utf-8")
    link = target / location
    if location == "shared":
        shared = tmp_path / "_shared"
        shared.mkdir()
        link = shared / "asset.sty"
    if link.exists():
        link.unlink()
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("OS does not grant symlink creation for this fixture")
    with pytest.raises(ProfileConfigurationError, match="^profile_invalid$"):
        load_profile_catalog(tmp_path)
