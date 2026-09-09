"""Fail-fast loader for trusted, source-controlled document profiles."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .contracts import DocumentProfile

_PROFILE_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_SAFE_RELATIVE = re.compile(r"^[A-Za-z0-9_.\-/]+$")


class ProfileConfigurationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProfileCatalog:
    version: str
    digest: str
    profiles: Mapping[str, DocumentProfile]
    root: Path

    def get(self, profile_id: str) -> DocumentProfile | None:
        return self.profiles.get(str(profile_id or "").strip().lower())

    def public_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "digest": self.digest[:16],
            "count": len(self.profiles),
            "profiles": [profile.public_dict() for profile in self.profiles.values()],
        }


def default_profile_root() -> Path:
    return Path(__file__).with_name("profile_data")


def _tree_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        relative = path.relative_to(directory).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _strings(value: object, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProfileConfigurationError(f"invalid_{field}")
    return tuple(dict.fromkeys(item.strip() for item in value if item.strip()))


def _load_profile(directory: Path) -> DocumentProfile:
    manifest = directory / "profile.toml"
    if not manifest.is_file():
        raise ProfileConfigurationError("manifest_missing")
    try:
        raw = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ProfileConfigurationError("manifest_invalid") from exc
    profile_id = str(raw.get("profile_id") or "").strip()
    entrypoint = str(raw.get("entrypoint") or "").strip()
    if not _PROFILE_ID.fullmatch(profile_id):
        raise ProfileConfigurationError("profile_id_invalid")
    if profile_id != directory.name:
        raise ProfileConfigurationError("profile_name_mismatch")
    if not _SAFE_RELATIVE.fullmatch(entrypoint) or entrypoint.startswith(("/", "../")):
        raise ProfileConfigurationError("entrypoint_invalid")
    if not (directory / entrypoint).is_file():
        raise ProfileConfigurationError("entrypoint_missing")
    digest = _tree_digest(directory)
    try:
        return DocumentProfile(
            profile_id=profile_id,
            version=int(raw.get("version") or 0),
            label_ru=str(raw.get("label_ru") or profile_id),
            kind=str(raw.get("kind") or ""),
            engine=str(raw.get("engine") or ""),
            entrypoint=entrypoint,
            documentclass=str(raw.get("documentclass") or ""),
            locale=str(raw.get("locale") or "en-US"),
            paper=str(raw.get("paper") or "a4"),
            orientation=str(raw.get("orientation") or "portrait"),
            bibliography_backend=str(raw.get("bibliography_backend") or "none"),
            bibliography_required=bool(raw.get("bibliography_required")),
            required_sections=_strings(raw.get("required_sections"), field="required_sections"),
            locked_fields=frozenset(_strings(raw.get("locked_fields"), field="locked_fields")),
            allowed_overrides=frozenset(
                _strings(raw.get("allowed_overrides"), field="allowed_overrides")
            ),
            anonymize_supported=bool(raw.get("anonymize_supported")),
            source_export=str(raw.get("source_export") or "forbidden"),
            max_pages=(int(raw["max_pages"]) if raw.get("max_pages") is not None else None),
            content_contract=str(raw.get("content_contract") or raw.get("kind") or "generic"),
            template_dir=str(directory),
            digest=digest,
        )
    except (TypeError, ValueError) as exc:
        raise ProfileConfigurationError("profile_invalid") from exc


def load_profile_catalog(root: Path | None = None) -> ProfileCatalog:
    profile_root = root or default_profile_root()
    if not profile_root.is_dir():
        raise ProfileConfigurationError("catalog_missing")
    profiles: dict[str, DocumentProfile] = {}
    for directory in sorted(item for item in profile_root.iterdir() if item.is_dir()):
        if directory.name.startswith("_"):
            continue
        profile = _load_profile(directory)
        if profile.profile_id in profiles:
            raise ProfileConfigurationError("duplicate_profile")
        profiles[profile.profile_id] = profile
    if not profiles:
        raise ProfileConfigurationError("catalog_empty")
    payload = [
        {"id": item.profile_id, "version": item.version, "digest": item.digest}
        for item in profiles.values()
    ]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return ProfileCatalog(
        version="s34.v1",
        digest=digest,
        profiles=MappingProxyType(profiles),
        root=profile_root,
    )
