"""Create and inspect versioned document projects inside a workspace."""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import secrets
import shlex
import tarfile
import tomllib
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from domain.documents import DocumentProfile, ProfileCatalog
from domain.files import parse_read, read_command, safe_path, write_command

RunCommand = Callable[..., Awaitable[Any]]
Snapshot = Callable[[Any, str], Awaitable[dict]]
_AUTHORING_BLOCK_ID = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
_VENDOR_PACKAGE_ID = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
_VENDOR_FILENAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_CONTENT_CONTRACT = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_EFFECTIVE_PROFILE_FIELDS = frozenset(
    {
        "schema_version",
        "base_profile_id",
        "base_profile_version",
        "vendor_package_id",
        "documentclass",
        "bibliography_style",
        "content_contract",
        "paper",
        "orientation",
        "max_pages",
        "required_sections",
        "export_allowed",
    }
)


class DocumentProjectError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _toml(profile: DocumentProfile, *, mode: str, locale: str) -> str:
    sections = ", ".join(f'"{item}"' for item in profile.required_sections)
    locked = ", ".join(f'"{item}"' for item in sorted(profile.locked_fields))
    allowed = ", ".join(f'"{item}"' for item in sorted(profile.allowed_overrides))
    return (
        "schema_version = 1\n"
        f'kind = "{profile.kind}"\n'
        f'profile_id = "{profile.profile_id}"\n'
        f"profile_version = {profile.version}\n"
        f'locale = "{locale}"\n'
        f'entrypoint = "{profile.entrypoint}"\n'
        f'engine = "{profile.engine}"\n'
        f'documentclass = "{profile.documentclass}"\n'
        f'paper = "{profile.paper}"\n'
        f'orientation = "{profile.orientation}"\n'
        f'mode = "{mode}"\n'
        f'bibliography_backend = "{profile.bibliography_backend}"\n'
        f"bibliography_required = {str(profile.bibliography_required).lower()}\n"
        f"required_sections = [{sections}]\n"
        f"locked_fields = [{locked}]\n"
        f"allowed_overrides = [{allowed}]\n"
        f"anonymize = {str(mode == 'submission' and profile.anonymize_supported).lower()}\n"
        f"max_pages = {profile.max_pages or 0}\n"
        f'source_export = "{profile.source_export}"\n'
        f'content_contract = "{profile.content_contract}"\n'
    )


def _add_file(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    info.mode = 0o644
    info.mtime = 1_704_067_200
    archive.addfile(info, io.BytesIO(payload))


def scaffold_archive(profile: DocumentProfile, *, mode: str, locale: str) -> bytes:
    output = io.BytesIO()
    profile_dir = Path(profile.template_dir)
    shared_dir = profile_dir.parent / "_shared"
    with tarfile.open(fileobj=output, mode="w") as archive:
        _add_file(archive, "document.toml", _toml(profile, mode=mode, locale=locale).encode())
        for base in (shared_dir, profile_dir):
            for path in sorted(item for item in base.rglob("*") if item.is_file()):
                if path.name == "profile.toml":
                    continue
                relative = path.relative_to(base).as_posix()
                _add_file(archive, relative, path.read_bytes())
        _add_file(
            archive,
            ".gitignore",
            b".gpthub-document/\nartifacts/**\n*.aux\n*.bbl\n*.bcf\n*.blg\n*.fdb_latexmk\n*.fls\n*.log\n*.out\n*.run.xml\n*.toc\n*.nav\n*.snm\n",
        )
    return output.getvalue()


def source_digest_command(root: str, project_path: str) -> str:
    target = safe_path(root, project_path)
    quoted = shlex.quote(target)
    return (
        f"find {quoted} -type f "
        "! -path '*/.git/*' ! -path '*/.gpthub-document/*' ! -path '*/artifacts/*' "
        "-print0 | sort -z | xargs -0 sha256sum 2>/dev/null | sha256sum | cut -d' ' -f1"
    )


class DocumentProjectService:
    def __init__(
        self,
        run_command: RunCommand,
        snapshot: Snapshot,
        catalog: ProfileCatalog,
    ) -> None:
        self._run = run_command
        self._snapshot = snapshot
        self.catalog = catalog

    async def create(
        self,
        item: Any,
        *,
        path: str,
        profile_id: str,
        mode: str,
        locale: str | None,
    ) -> dict[str, object]:
        profile = self.catalog.get(profile_id)
        if profile is None:
            raise DocumentProjectError("profile_missing")
        if mode not in {"draft", "submission", "camera_ready"}:
            raise DocumentProjectError("invalid_project")
        target = safe_path(item.policy.root, path)
        relative = posixpath.relpath(target, item.policy.root)
        if relative in {".", ""} or relative.startswith("../"):
            raise DocumentProjectError("invalid_project")
        archive = scaffold_archive(profile, mode=mode, locale=locale or profile.locale)
        stage = f"{item.policy.root}/.gpthub-document/scaffold-{secrets.token_hex(8)}"
        parent = posixpath.dirname(target)
        command = (
            f"if [ -e {shlex.quote(target)} ]; then echo __EXISTS__; exit 0; fi; "
            f"mkdir -p {shlex.quote(parent)} {shlex.quote(posixpath.dirname(stage))} && "
            f"rm -rf {shlex.quote(stage)} && mkdir {shlex.quote(stage)} && "
            f"if ! tar -C {shlex.quote(stage)} -xf -; then "
            f"rm -rf {shlex.quote(stage)}; echo __FAILED__; exit 0; fi; "
            f"if mv {shlex.quote(stage)} {shlex.quote(target)}; then echo __OK__; "
            f"else rm -rf {shlex.quote(stage)}; echo __FAILED__; fi"
        )
        result = await self._run(item, command, stdin_payload=archive)
        if "__EXISTS__" in result.stdout:
            raise DocumentProjectError("project_exists")
        if "__OK__" not in result.stdout:
            raise DocumentProjectError("runtime_unavailable")
        await self._snapshot(item, "document_scaffold")
        return {
            "path": relative,
            "profile": profile.public_dict(),
            "revision_changed": True,
        }

    async def manifest(self, item: Any, path: str) -> tuple[dict[str, object], DocumentProfile]:
        project = safe_path(item.policy.root, path)
        result = await self._run(item, read_command(item.policy.root, f"{project}/document.toml"))
        try:
            content, truncated = parse_read(result.stdout)
            if truncated:
                raise DocumentProjectError("invalid_project")
            raw = tomllib.loads(content)
        except (FileNotFoundError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise DocumentProjectError("invalid_project") from exc
        profile = self.catalog.get(str(raw.get("profile_id") or ""))
        if profile is None:
            raise DocumentProjectError("profile_missing")
        invariants: dict[str, object] = {
            "schema_version": 1,
            "kind": profile.kind,
            "profile_version": profile.version,
            "entrypoint": profile.entrypoint,
            "engine": profile.engine,
            "documentclass": profile.documentclass,
            "bibliography_backend": profile.bibliography_backend,
            "bibliography_required": profile.bibliography_required,
            "required_sections": list(profile.required_sections),
            "locked_fields": sorted(profile.locked_fields),
            "allowed_overrides": sorted(profile.allowed_overrides),
            "source_export": profile.source_export,
            "content_contract": profile.content_contract,
        }
        if any(raw.get(field) != value for field, value in invariants.items()):
            raise DocumentProjectError("profile_mismatch")
        if "paper" not in profile.allowed_overrides and raw.get("paper") != profile.paper:
            raise DocumentProjectError("profile_mismatch")
        if (
            "orientation" not in profile.allowed_overrides
            and raw.get("orientation") != profile.orientation
        ):
            raise DocumentProjectError("profile_mismatch")
        if "page_limit" not in profile.allowed_overrides:
            expected_pages = profile.max_pages or 0
            if raw.get("max_pages") != expected_pages:
                raise DocumentProjectError("profile_mismatch")
        if str(raw.get("mode") or "") not in {"draft", "submission", "camera_ready"}:
            raise DocumentProjectError("invalid_project")
        anonymize = raw.get("anonymize")
        if not isinstance(anonymize, bool) or (anonymize and not profile.anonymize_supported):
            raise DocumentProjectError("profile_mismatch")
        if raw.get("mode") == "submission" and profile.anonymize_supported and not anonymize:
            raise DocumentProjectError("profile_mismatch")
        _effective, resolved = await self.effective_profile(item, path, profile)
        return raw, resolved

    async def effective_profile(
        self,
        item: Any,
        path: str,
        base: DocumentProfile,
    ) -> tuple[dict[str, object] | None, DocumentProfile]:
        """Resolve a validated project-local overlay without weakening the base policy."""

        project = safe_path(item.policy.root, path)
        result = await self._run(
            item,
            read_command(item.policy.root, f"{project}/.gpthub-effective-profile.json"),
        )
        try:
            content, truncated = parse_read(result.stdout)
            raw = json.loads(content)
        except (FileNotFoundError, UnicodeError, ValueError):
            return None, base
        if truncated or not isinstance(raw, dict):
            raise DocumentProjectError("vendor_profile_invalid")
        required = {
            "schema_version": 1,
            "base_profile_id": base.profile_id,
            "base_profile_version": base.version,
            "paper": base.paper,
            "orientation": base.orientation,
            "export_allowed": False,
        }
        if any(raw.get(key) != value for key, value in required.items()):
            raise DocumentProjectError("vendor_profile_invalid")
        package_id = str(raw.get("vendor_package_id") or "")
        documentclass = str(raw.get("documentclass") or "")
        bibliography_style = str(raw.get("bibliography_style") or "")
        content_contract = str(raw.get("content_contract") or "")
        max_pages = raw.get("max_pages")
        sections = raw.get("required_sections")
        if (
            set(raw) != _EFFECTIVE_PROFILE_FIELDS
            or not _VENDOR_PACKAGE_ID.fullmatch(package_id)
            or not _VENDOR_FILENAME.fullmatch(documentclass)
            or bibliography_style
            and not _VENDOR_FILENAME.fullmatch(bibliography_style)
            or not _CONTENT_CONTRACT.fullmatch(content_contract)
            or not isinstance(max_pages, int)
            or isinstance(max_pages, bool)
            or max_pages < 0
            or base.max_pages
            and (max_pages == 0 or max_pages > base.max_pages)
            or not isinstance(sections, list)
            or len(sections) > 32
            or any(not isinstance(value, str) or not 1 <= len(value) <= 120 for value in sections)
        ):
            raise DocumentProjectError("vendor_profile_invalid")
        required_sections = tuple(dict.fromkeys((*base.required_sections, *sections)))
        digest = hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        resolved = replace(
            base,
            documentclass=documentclass,
            content_contract=content_contract,
            required_sections=required_sections,
            max_pages=max_pages or None,
            source_export="forbidden",
            digest=digest,
        )
        return raw, resolved

    async def digest(self, item: Any, path: str) -> str:
        result = await self._run(item, source_digest_command(item.policy.root, path))
        value = str(result.stdout or "").strip().splitlines()[0:1]
        if not value or len(value[0]) != 64:
            raise DocumentProjectError("invalid_project")
        try:
            bytes.fromhex(value[0])
        except ValueError as exc:
            raise DocumentProjectError("invalid_project") from exc
        return value[0]

    async def _authoring_manifest(self, item: Any, path: str) -> dict[str, object] | None:
        project = safe_path(item.policy.root, path)
        result = await self._run(
            item,
            read_command(item.policy.root, f"{project}/.gpthub-authoring.json"),
        )
        try:
            content, truncated = parse_read(result.stdout)
            raw = json.loads(content)
        except FileNotFoundError:
            return None
        except (UnicodeError, ValueError) as exc:
            raise DocumentProjectError("authoring_invalid") from exc
        if truncated or not isinstance(raw, dict):
            raise DocumentProjectError("authoring_invalid")
        return raw

    @staticmethod
    def _authoring_facts(raw: dict[str, object]) -> tuple[int, str, dict[str, object], list]:
        version = raw.get("draft_version")
        digest = str(raw.get("draft_digest") or "")
        draft = raw.get("draft")
        blocks = draft.get("blocks") if isinstance(draft, dict) else None
        if (
            raw.get("schema_version") != 1
            or not isinstance(version, int)
            or version < 1
            or not isinstance(draft, dict)
            or draft.get("version") != version
            or not isinstance(blocks, list)
            or not 1 <= len(blocks) <= 120
            or len(digest) != 64
        ):
            raise DocumentProjectError("authoring_invalid")
        try:
            bytes.fromhex(digest)
        except ValueError as exc:
            raise DocumentProjectError("authoring_invalid") from exc
        computed = hashlib.sha256(
            json.dumps(
                draft,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if computed != digest:
            raise DocumentProjectError("authoring_invalid")
        return version, digest, draft, blocks

    async def authoring(self, item: Any, path: str) -> tuple[int, str]:
        raw = await self._authoring_manifest(item, path)
        if raw is None:
            return 0, ""
        version, digest, _draft, _blocks = self._authoring_facts(raw)
        return version, digest

    async def authoring_state(self, item: Any, path: str) -> dict[str, object]:
        await self.manifest(item, path)
        raw = await self._authoring_manifest(item, path)
        if raw is None:
            raise DocumentProjectError("authoring_missing")
        version, digest, draft, blocks = self._authoring_facts(raw)
        intent = raw.get("intent")
        if not isinstance(intent, dict):
            raise DocumentProjectError("authoring_invalid")
        block_ids = {
            str(block.get("block_id") or block.get("id") or "")
            for block in blocks
            if isinstance(block, dict)
        }
        if len(block_ids) != len(blocks) or any(
            not _AUTHORING_BLOCK_ID.fullmatch(block_id) for block_id in block_ids
        ):
            raise DocumentProjectError("authoring_invalid")
        raw_files = raw.get("block_files")
        block_files: dict[str, str] = {}
        if isinstance(raw_files, dict) and len(raw_files) <= 120:
            for path_value, block_value in raw_files.items():
                relative = str(path_value or "")
                block_id = str(block_value or "")
                if (
                    relative.startswith("content/")
                    and relative.endswith(".tex")
                    and 1 <= len(relative) <= 200
                    and block_id in block_ids
                ):
                    block_files[block_id] = relative
        return {
            "schema_version": 1,
            "authoring_version": version,
            "draft_digest": digest,
            "intent": intent,
            "draft": draft,
            "block_files": block_files,
        }

    async def block_provenance(self, item: Any, path: str) -> dict[str, str]:
        try:
            state = await self.authoring_state(item, path)
        except DocumentProjectError as exc:
            if exc.code == "authoring_missing":
                return {}
            raise
        mapping = state.get("block_files")
        if not isinstance(mapping, dict):
            return {}
        return {
            posixpath.basename(str(relative)): str(block_id)
            for block_id, relative in mapping.items()
        }

    async def status(self, item: Any, path: str) -> dict[str, object]:
        raw, profile = await self.manifest(item, path)
        authoring_version, draft_digest = await self.authoring(item, path)
        base = self.catalog.get(str(raw.get("profile_id") or ""))
        effective, _resolved = (
            await self.effective_profile(item, path, base) if base is not None else (None, profile)
        )
        return {
            "path": posixpath.relpath(safe_path(item.policy.root, path), item.policy.root),
            "kind": profile.kind,
            "profile": profile.public_dict(),
            "mode": str(raw.get("mode") or "draft"),
            "locale": str(raw.get("locale") or profile.locale),
            "source_digest": await self.digest(item, path),
            "authoring_version": authoring_version,
            "draft_digest": draft_digest or None,
            "authoring_state": "ready" if authoring_version else "absent",
            "effective_profile": (
                {
                    key: effective.get(key)
                    for key in (
                        "base_profile_id",
                        "vendor_package_id",
                        "content_contract",
                        "paper",
                        "orientation",
                        "max_pages",
                    )
                }
                if effective is not None
                else None
            ),
        }

    async def apply_profile(
        self,
        item: Any,
        *,
        path: str,
        profile_id: str,
        mode: str | None = None,
        locale: str | None = None,
        target_path: str | None = None,
    ) -> dict[str, object]:
        current, current_profile = await self.manifest(item, path)
        profile = self.catalog.get(profile_id)
        if profile is None:
            raise DocumentProjectError("profile_missing")
        next_mode = str(mode or current.get("mode") or "draft")
        if next_mode not in {"draft", "submission", "camera_ready"}:
            raise DocumentProjectError("invalid_project")
        next_locale = str(locale or current.get("locale") or profile.locale).strip()
        if not next_locale or len(next_locale) > 24:
            raise DocumentProjectError("invalid_project")
        source = safe_path(item.policy.root, path)
        source_relative = posixpath.relpath(source, item.policy.root)
        if profile.profile_id != current_profile.profile_id:
            if not target_path:
                raise DocumentProjectError("target_path_required")
            target = safe_path(item.policy.root, target_path)
            target_relative = posixpath.relpath(target, item.policy.root)
            if target_relative in {".", ""} or target_relative.startswith("../"):
                raise DocumentProjectError("invalid_project")
            archive = scaffold_archive(profile, mode=next_mode, locale=next_locale)
            stage = f"{item.policy.root}/.gpthub-document/clone-{secrets.token_hex(8)}"
            parent = posixpath.dirname(target)
            same_contract = current_profile.content_contract == profile.content_contract
            content_names = "figures bibliography" + (" content" if same_contract else "")
            migration = ""
            content_status = "copied" if same_contract else "content_migration_required"
            if not same_contract:
                migration = (
                    f"mkdir -p {shlex.quote(stage + '/migration/source')} && "
                    f"(cd {shlex.quote(source)} && "
                    "find . -type d "
                    "\\( -name .git -o -name .gpthub-document -o -name artifacts "
                    "-o -name vendor \\) "
                    "-prune -o -type f -name '*.tex' -print0 | "
                    f"tar --null -T - -cf - 2>/dev/null) | "
                    f"tar -C {shlex.quote(stage + '/migration/source')} -xf - 2>/dev/null; "
                )
            copy_shared = (
                f"(cd {shlex.quote(source)} && "
                f"find {content_names} -type f -print0 2>/dev/null | "
                f"tar --null -T - -cf - 2>/dev/null) | "
                f"tar -C {shlex.quote(stage)} -xf - 2>/dev/null; "
            )
            command = (
                f"if [ -e {shlex.quote(target)} ]; then echo __EXISTS__; exit 0; fi; "
                f"mkdir -p {shlex.quote(parent)} {shlex.quote(posixpath.dirname(stage))} && "
                f"rm -rf {shlex.quote(stage)} && mkdir {shlex.quote(stage)} && "
                f"tar -C {shlex.quote(stage)} -xf - || "
                f"{{ rm -rf {shlex.quote(stage)}; echo __FAILED__; exit 0; }}; "
                f"{copy_shared}{migration}"
                f"if mv {shlex.quote(stage)} {shlex.quote(target)}; then echo __OK__; "
                f"else rm -rf {shlex.quote(stage)}; echo __FAILED__; fi"
            )
            result = await self._run(item, command, stdin_payload=archive)
            if "__EXISTS__" in result.stdout:
                raise DocumentProjectError("project_exists")
            if "__OK__" not in result.stdout:
                raise DocumentProjectError("runtime_unavailable")
            await self._snapshot(item, "document_profile")
            return {
                "outcome": "cloned",
                "path": target_relative,
                "source_path": source_relative,
                "profile": profile.public_dict(),
                "mode": next_mode,
                "locale": next_locale,
                "content_status": content_status,
                "revision_changed": True,
            }
        command, body = write_command(
            item.policy.root,
            f"{source}/document.toml",
            _toml(profile, mode=next_mode, locale=next_locale),
        )
        result = await self._run(item, command, stdin_payload=body)
        if "__OK__" not in result.stdout:
            raise DocumentProjectError("runtime_unavailable")
        await self._snapshot(item, "document_profile")
        return {
            "outcome": "updated",
            "path": source_relative,
            "profile": profile.public_dict(),
            "mode": next_mode,
            "locale": next_locale,
            "revision_changed": True,
        }
