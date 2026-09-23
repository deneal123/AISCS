"""Compiled editorial skills paired one-to-one with workspace profiles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .profile_contract import DOCUMENT_PROFILE_IDS, DOCUMENT_SKILL_CONTRACT_VERSION
from .skills import DocumentSkill, skill_for_profile


@dataclass(frozen=True, slots=True)
class DocumentSkillCatalog:
    version: str
    digest: str
    skills: Mapping[str, DocumentSkill]

    def get(self, profile_id: str) -> DocumentSkill | None:
        return self.skills.get(str(profile_id or ""))

    def safe_manifest(self) -> dict[str, object]:
        return {
            "version": self.version,
            "digest": self.digest,
            "profiles": sorted(self.skills),
            "count": len(self.skills),
        }

    def semantic_instruction(self, profile_id: str) -> str:
        skill = self.get(profile_id) or self.skills["generic_document"]
        checks = "\n".join(f"- {item}" for item in skill.checklist[-3:])
        return (
            "Create a semantic document draft using only the requested structured function. "
            "Never emit LaTeX, packages, file paths, URLs, or bibliography records. Every "
            "block_id must be stable, unique, lowercase, and meaningful. Citation blocks and "
            "evidence-backed slide blocks may reference only source IDs present in the private "
            "evidence context.\n"
            f"Editorial profile: {skill.instruction}\nChecks:\n{checks}"
        )


def compile_document_skill_catalog() -> DocumentSkillCatalog:
    skills = {profile_id: skill_for_profile(profile_id) for profile_id in DOCUMENT_PROFILE_IDS}
    if set(skills) != set(DOCUMENT_PROFILE_IDS):
        raise RuntimeError("document_skill_profile_mismatch")
    rows = [
        {
            "profile_id": profile_id,
            "skill_id": skill.skill_id,
            "instruction": skill.instruction,
            "checklist": list(skill.checklist),
        }
        for profile_id, skill in sorted(skills.items())
    ]
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DocumentSkillCatalog(DOCUMENT_SKILL_CONTRACT_VERSION, digest, MappingProxyType(skills))


DOCUMENT_SKILL_CATALOG = compile_document_skill_catalog()

__all__ = [
    "DOCUMENT_SKILL_CATALOG",
    "DocumentSkillCatalog",
    "compile_document_skill_catalog",
]
