"""Offline-safe mirror of Document Forge profile identities.

The workspace sidecar owns templates and compiler policy. Agents only need the
versioned identifiers for deterministic skill binding and capability digests.
"""

DOCUMENT_PROFILE_CONTRACT_VERSION = "s35.v1"
DOCUMENT_SKILL_CONTRACT_VERSION = "s35.v1"
DOCUMENT_PROFILE_IDS = (
    "aaai_conference",
    "beamer_16_9",
    "generic_article",
    "generic_document",
    "generic_report",
    "ieee_journal",
    "legal_ru",
)

# Formatting requirements are mirrored from workspace profile manifests and
# verified by the root parity gate. They are deterministic profile facts, not
# suggestions that an authoring model may omit or rename.
DOCUMENT_PROFILE_REQUIRED_SECTIONS = {
    "aaai_conference": ("Abstract", "Introduction", "Conclusion", "References"),
    "beamer_16_9": (),
    "generic_article": ("Аннотация", "Введение", "Заключение", "Литература"),
    "generic_document": (),
    "generic_report": ("Цель", "Результаты", "Выводы"),
    "ieee_journal": ("Abstract", "Introduction", "Conclusion", "References"),
    "legal_ru": ("Предмет документа", "Подписи сторон"),
}

__all__ = [
    "DOCUMENT_PROFILE_CONTRACT_VERSION",
    "DOCUMENT_PROFILE_IDS",
    "DOCUMENT_PROFILE_REQUIRED_SECTIONS",
    "DOCUMENT_SKILL_CONTRACT_VERSION",
]
