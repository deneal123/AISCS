"""Проверка встроенных шаблонов без Docker, сети и пользовательских проектов."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from domain.documents import ProfileConfigurationError, load_profile_catalog

from .projects import scaffold_archive

REQUIRED_BUILTIN_PROFILES = frozenset(
    {
        "aaai_conference",
        "beamer_16_9",
        "generic_article",
        "generic_document",
        "generic_report",
        "ieee_journal",
        "legal_ru",
    }
)


def verify_document_bundle(root: Path | None = None) -> int:
    catalog = load_profile_catalog(root)
    if not REQUIRED_BUILTIN_PROFILES <= catalog.profiles.keys():
        raise ProfileConfigurationError("profile_bundle_incomplete")
    for profile in catalog.profiles.values():
        payload = scaffold_archive(profile, mode="draft", locale=profile.locale)
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            required = {"document.toml", profile.entrypoint, "gpthub-core.sty"}
            if profile.bibliography_required:
                required.add("bibliography/references.bib")
            if not required <= set(archive.getnames()):
                raise ProfileConfigurationError("profile_bundle_incomplete")
            for name in required:
                item = archive.extractfile(name)
                if item is None or not item.read().strip():
                    raise ProfileConfigurationError("profile_bundle_incomplete")
    return len(catalog.profiles)


def main() -> int:
    try:
        count = verify_document_bundle()
    except (OSError, ValueError, tarfile.TarError, ProfileConfigurationError):
        print("Встроенные шаблоны PDF неполны; code=profile_bundle_incomplete")
        return 1
    print(f"Встроенные шаблоны PDF проверены: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
