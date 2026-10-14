"""Typed editable project settings without weakening the trusted profile."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import replace

from .contracts import DocumentProfile

_LOCALE = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,3}")


def validate_locale(value: object) -> str:
    if not isinstance(value, str) or len(value) > 24 or not _LOCALE.fullmatch(value):
        raise ValueError("invalid_project")
    return value


def resolve_project_settings(raw: dict[str, object], profile: DocumentProfile) -> DocumentProfile:
    """A run-local immutable projection; the source-controlled catalog is unchanged."""
    if (
        type(raw.get("schema_version")) is not int
        or type(raw.get("profile_version")) is not int
        or type(raw.get("bibliography_required")) is not bool
    ):
        raise ValueError("profile_mismatch")
    validate_locale(raw.get("locale"))
    paper, orientation, limit = raw.get("paper"), raw.get("orientation"), raw.get("max_pages")
    if (
        not isinstance(paper, str)
        or paper not in {"a4", "letter", "slide_16_9"}
        or not isinstance(orientation, str)
        or orientation not in {"portrait", "landscape"}
        or type(limit) is not int
        or not 0 <= limit <= 10_000
        or (profile.max_pages is not None and not 0 < limit <= profile.max_pages)
    ):
        raise ValueError("profile_mismatch")
    return replace(profile, paper=paper, orientation=orientation, max_pages=limit or None)


def update_project_mode(source: str, *, mode: str, locale: str, anonymize: bool) -> str:
    """Change three canonical machine fields; never reconstruct user metadata.

    Noncanonical multiline/quoted keys are rejected before write rather than
    guessed. All untouched TOML data and bytes, including comments, are retained.
    """
    validate_locale(locale)
    if mode not in {"draft", "submission", "camera_ready"}:
        raise ValueError("invalid_project")
    try:
        before = tomllib.loads(source)
    except tomllib.TOMLDecodeError:
        raise ValueError("invalid_project") from None
    updates = {"mode": mode, "locale": locale, "anonymize": anonymize}
    for key, value in updates.items():
        literal = (
            r"(?:true|false)\b" if key == "anonymize" else r"(?:'[^'\n]*'|\"(?:\\.|[^\"\\\n])*\")"
        )
        pattern = re.compile(rf"(?m)^([ \t]*{key}[ \t]*=[ \t]*){literal}(?=[ \t]*(?:#|$))")
        encoded = json.dumps(value)
        source, count = pattern.subn(lambda match, encoded=encoded: match[1] + encoded, source)
        if count != 1:
            raise ValueError("invalid_project")
    try:
        after = tomllib.loads(source)
    except tomllib.TOMLDecodeError:
        raise ValueError("invalid_project") from None
    if after != {**before, **updates}:
        raise ValueError("invalid_project")
    return source
