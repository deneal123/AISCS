"""Validate and atomically install untrusted project-local LaTeX vendor kits."""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import secrets
import shlex
import stat
import tarfile
import tomllib
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from domain.files import safe_path

from application.importer import ImportRefused, fetch

from .projects import DocumentProjectError, DocumentProjectService

MAX_VENDOR_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_VENDOR_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_VENDOR_FILE_BYTES = 8 * 1024 * 1024
MAX_VENDOR_FILES = 256
MAX_COMPRESSION_RATIO = 200
SAFE_VENDOR_EXTENSIONS = frozenset(
    {
        ".bbx",
        ".bib",
        ".bst",
        ".cbx",
        ".cfg",
        ".clo",
        ".cls",
        ".def",
        ".eps",
        ".jpeg",
        ".jpg",
        ".lic",
        ".md",
        ".pdf",
        ".png",
        ".sty",
        ".tex",
        ".toml",
        ".txt",
    }
)
ENTRY_EXTENSIONS = frozenset(
    {".bbx", ".bst", ".cbx", ".cfg", ".clo", ".cls", ".def", ".sty", ".tex"}
)
TEXT_EXTENSIONS = frozenset(
    {
        ".bbx",
        ".bib",
        ".bst",
        ".cbx",
        ".cfg",
        ".clo",
        ".cls",
        ".def",
        ".md",
        ".sty",
        ".tex",
        ".toml",
        ".txt",
    }
)
FORBIDDEN_TEX = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        rb"\\write\s*18\b",
        rb"\\immediate\s*\\write\s*18\b",
        rb"\\directlua\b",
        rb"\\latelua\b",
        rb"\\openout\b",
        rb"\\openin\b",
        rb"\\read\b",
        rb"\\ShellEscape\b",
    )
)
PACKAGE_ID = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
OVERLAY_METADATA = ".gpthub-overlay.toml"

RunCommand = Callable[..., Awaitable[Any]]
Snapshot = Callable[[Any, str], Awaitable[dict[str, Any]]]
Revision = Callable[[Any], Awaitable[str]]
Fetch = Callable[..., Awaitable[bytes]]


class VendorOverlayError(DocumentProjectError):
    """A bounded failure while validating or publishing a vendor overlay."""


@dataclass(frozen=True, slots=True)
class VendorOverlayPackage:
    package_id: str
    version: str
    license_name: str
    digest: str
    file_count: int
    expanded_bytes: int
    archive: bytes

    def public_dict(self) -> dict[str, object]:
        return {
            "package_id": self.package_id,
            "version": self.version,
            "license": self.license_name,
            "digest": self.digest,
            "file_count": self.file_count,
            "expanded_bytes": self.expanded_bytes,
            "trusted": False,
            "export_allowed": False,
        }


def _normalized_name(value: str) -> PurePosixPath:
    if not value or "\x00" in value or "\\" in value:
        raise VendorOverlayError("vendor_archive_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise VendorOverlayError("vendor_archive_invalid")
    if path.parts[0].endswith(":"):
        raise VendorOverlayError("vendor_archive_invalid")
    return path


def _is_regular(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return not mode or stat.S_IFMT(mode) in {0, stat.S_IFREG}


def _manifest_root(files: dict[str, zipfile.ZipInfo]) -> tuple[str, str]:
    manifests = [name for name in files if name == "vendor.toml" or name.endswith("/vendor.toml")]
    if len(manifests) != 1:
        raise VendorOverlayError("vendor_manifest_invalid")
    manifest_name = manifests[0]
    root = manifest_name[: -len("vendor.toml")].rstrip("/")
    if root and any(not name.startswith(f"{root}/") for name in files):
        raise VendorOverlayError("vendor_archive_invalid")
    return root, manifest_name


def _relative_name(name: str, root: str) -> str:
    relative = name[len(root) + 1 :] if root else name
    path = _normalized_name(relative)
    if any(part.startswith(".") for part in path.parts):
        raise VendorOverlayError("vendor_archive_invalid")
    if path.suffix.lower() not in SAFE_VENDOR_EXTENSIONS:
        raise VendorOverlayError("vendor_archive_invalid")
    return path.as_posix()


def _read_manifest(payload: bytes, available: set[str]) -> tuple[str, str, str]:
    try:
        raw = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise VendorOverlayError("vendor_manifest_invalid") from exc
    allowed = {"schema_version", "package_id", "version", "license", "entry_files"}
    if set(raw) - allowed or raw.get("schema_version") != 1:
        raise VendorOverlayError("vendor_manifest_invalid")
    package_id = str(raw.get("package_id") or "")
    version = str(raw.get("version") or "")
    license_name = str(raw.get("license") or "").strip()
    entry_files = raw.get("entry_files")
    if not PACKAGE_ID.fullmatch(package_id) or not VERSION.fullmatch(version):
        raise VendorOverlayError("vendor_manifest_invalid")
    if not license_name or len(license_name) > 120 or any(ord(char) < 32 for char in license_name):
        raise VendorOverlayError("vendor_manifest_invalid")
    if not isinstance(entry_files, list) or not 1 <= len(entry_files) <= 32:
        raise VendorOverlayError("vendor_manifest_invalid")
    for value in entry_files:
        if not isinstance(value, str):
            raise VendorOverlayError("vendor_manifest_invalid")
        name = _normalized_name(value).as_posix()
        if name not in available or PurePosixPath(name).suffix.lower() not in ENTRY_EXTENSIONS:
            raise VendorOverlayError("vendor_manifest_invalid")
    return package_id, version, license_name


def _metadata(
    package_id: str, version: str, license_name: str, digest: str, count: int, size: int
) -> bytes:
    return (
        "schema_version = 1\n"
        f'package_id = "{package_id}"\n'
        f'version = "{version}"\n'
        f"license = {json.dumps(license_name, ensure_ascii=False)}\n"
        f'digest = "{digest}"\n'
        f"file_count = {count}\n"
        f"expanded_bytes = {size}\n"
        "trusted = false\n"
        "export_allowed = false\n"
    ).encode()


def validate_vendor_archive(payload: bytes) -> VendorOverlayPackage:
    """Return a deterministic safe tar package or reject the whole archive."""

    if not payload or len(payload) > MAX_VENDOR_ARCHIVE_BYTES:
        raise VendorOverlayError("vendor_too_large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise VendorOverlayError("vendor_archive_invalid") from exc
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if not infos or len(infos) > MAX_VENDOR_FILES:
            raise VendorOverlayError("vendor_too_large")
        indexed: dict[str, zipfile.ZipInfo] = {}
        folded: set[str] = set()
        expanded = 0
        for info in infos:
            name = _normalized_name(info.filename).as_posix()
            if info.flag_bits & 1 or not _is_regular(info):
                raise VendorOverlayError("vendor_unsafe")
            if name.casefold() in folded:
                raise VendorOverlayError("vendor_archive_invalid")
            folded.add(name.casefold())
            indexed[name] = info
            expanded += info.file_size
            compressed = max(1, info.compress_size)
            if (
                info.file_size > MAX_VENDOR_FILE_BYTES
                or info.file_size / compressed > MAX_COMPRESSION_RATIO
            ):
                raise VendorOverlayError("vendor_too_large")
        if expanded > MAX_VENDOR_EXPANDED_BYTES:
            raise VendorOverlayError("vendor_too_large")
        root, manifest_name = _manifest_root(indexed)
        contents: dict[str, bytes] = {}
        for name, info in indexed.items():
            relative = _relative_name(name, root)
            try:
                contents[relative] = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise VendorOverlayError("vendor_archive_invalid") from exc
        manifest_relative = _relative_name(manifest_name, root)
        package_id, version, license_name = _read_manifest(
            contents[manifest_relative], set(contents)
        )
        for name, content in contents.items():
            if PurePosixPath(name).suffix.lower() in TEXT_EXTENSIONS and any(
                pattern.search(content) for pattern in FORBIDDEN_TEX
            ):
                raise VendorOverlayError("vendor_unsafe")
        digest = hashlib.sha256(payload).hexdigest()
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as target:
            for name in sorted(contents):
                info = tarfile.TarInfo(name)
                info.size = len(contents[name])
                info.mode = 0o644
                info.mtime = 1_704_067_200
                target.addfile(info, io.BytesIO(contents[name]))
            metadata = _metadata(
                package_id,
                version,
                license_name,
                digest,
                len(contents),
                expanded,
            )
            info = tarfile.TarInfo(OVERLAY_METADATA)
            info.size = len(metadata)
            info.mode = 0o644
            info.mtime = 1_704_067_200
            target.addfile(info, io.BytesIO(metadata))
    return VendorOverlayPackage(
        package_id=package_id,
        version=version,
        license_name=license_name,
        digest=digest,
        file_count=len(contents),
        expanded_bytes=expanded,
        archive=output.getvalue(),
    )


def _publish_command(root: str, project_path: str, package: VendorOverlayPackage) -> str:
    project = safe_path(root, project_path)
    vendor = safe_path(root, f"{project}/vendor")
    target = safe_path(root, f"{vendor}/{package.package_id}")
    stage = safe_path(root, f".gpthub-document/vendor-{secrets.token_hex(8)}")
    digest_line = f'digest = "{package.digest}"'
    return (
        f"if [ -L {shlex.quote(project)} ] || [ ! -d {shlex.quote(project)} ] || "
        f"[ -L {shlex.quote(vendor)} ]; then echo __FAILED__; exit 0; fi; "
        f"if [ -e {shlex.quote(target)} ] || [ -L {shlex.quote(target)} ]; then "
        f"if grep -Fqx {shlex.quote(digest_line)} "
        f"{shlex.quote(target + '/' + OVERLAY_METADATA)} 2>/dev/null; "
        "then echo __KEPT__; else echo __COLLISION__; fi; exit 0; fi; "
        f"mkdir -p {shlex.quote(posixpath.dirname(stage))} {shlex.quote(vendor)} && "
        f"rm -rf {shlex.quote(stage)} && mkdir {shlex.quote(stage)} && "
        f"if ! tar -C {shlex.quote(stage)} -xf -; then rm -rf {shlex.quote(stage)}; "
        "echo __FAILED__; exit 0; fi; "
        f"if mv {shlex.quote(stage)} {shlex.quote(target)}; then echo __IMPORTED__; "
        f"else rm -rf {shlex.quote(stage)}; echo __FAILED__; fi"
    )


def _list_command(root: str, project_path: str) -> str:
    project = safe_path(root, project_path)
    script = (
        "import json,pathlib,tomllib,sys\n"
        "root=pathlib.Path(sys.argv[1]); out=[]\n"
        "if root.is_symlink(): print('[]'); raise SystemExit(0)\n"
        "for path in sorted(root.glob('*/.gpthub-overlay.toml')):\n"
        " try:\n"
        "  if path.is_symlink() or path.parent.is_symlink(): continue\n"
        "  raw=tomllib.loads(path.read_text(encoding='utf-8'))\n"
        "  if raw.get('schema_version')!=1: continue\n"
        "  keys=('package_id','version','license','digest','file_count',"
        "'expanded_bytes','trusted','export_allowed')\n"
        "  out.append({k:raw.get(k) for k in keys})\n"
        " except (OSError,UnicodeError,tomllib.TOMLDecodeError): pass\n"
        "print(json.dumps(out,separators=(',',':')))\n"
    )
    return f"python3 -c {shlex.quote(script)} {shlex.quote(project + '/vendor')}"


def _public_overlay(row: object) -> dict[str, object] | None:
    if not isinstance(row, dict):
        return None
    package_id = str(row.get("package_id") or "")
    version = str(row.get("version") or "")
    license_name = row.get("license")
    file_count = row.get("file_count")
    if (
        not PACKAGE_ID.fullmatch(package_id)
        or not VERSION.fullmatch(version)
        or not isinstance(license_name, str)
        or not license_name
        or len(license_name) > 120
        or any(ord(char) < 32 for char in license_name)
        or not isinstance(file_count, int)
        or isinstance(file_count, bool)
        or not 1 <= file_count <= MAX_VENDOR_FILES
    ):
        return None
    return {
        "package_id": package_id,
        "version": version,
        "license": license_name,
        "file_count": file_count,
        "trusted": False,
        "export_allowed": False,
    }


class DocumentVendorOverlayService:
    def __init__(
        self,
        run_command: RunCommand,
        snapshot: Snapshot,
        revision: Revision,
        projects: DocumentProjectService,
        fetcher: Fetch = fetch,
    ) -> None:
        self._run = run_command
        self._snapshot = snapshot
        self._revision = revision
        self._projects = projects
        self._fetch = fetcher

    async def list(self, item: Any, path: str) -> list[dict[str, object]]:
        await self._projects.manifest(item, path)
        result = await self._run(item, _list_command(item.policy.root, path))
        try:
            rows = json.loads(str(result.stdout or "[]"))
        except (TypeError, ValueError):
            return []
        if not isinstance(rows, list):
            return []
        safe_rows = (_public_overlay(row) for row in rows)
        return [row for row in safe_rows if row is not None]

    async def apply(
        self,
        item: Any,
        *,
        path: str,
        source_url: str,
        source_sha256: str | None,
        expected_revision: str,
    ) -> dict[str, object]:
        if await self._revision(item) != expected_revision:
            raise VendorOverlayError("revision_conflict")
        await self._projects.manifest(item, path)
        try:
            payload = await self._fetch(source_url)
        except ImportRefused as exc:
            raise VendorOverlayError("vendor_source_unavailable") from exc
        digest = hashlib.sha256(payload).hexdigest()
        if source_sha256 and (not SHA256.fullmatch(source_sha256) or digest != source_sha256):
            raise VendorOverlayError("vendor_integrity")
        package = validate_vendor_archive(payload)
        if await self._revision(item) != expected_revision:
            raise VendorOverlayError("revision_conflict")
        result = await self._run(
            item,
            _publish_command(item.policy.root, path, package),
            stdin_payload=package.archive,
        )
        output = str(result.stdout or "")
        if "__COLLISION__" in output:
            raise VendorOverlayError("vendor_collision")
        if "__KEPT__" in output:
            outcome = "kept"
            revision_changed = False
        elif "__IMPORTED__" in output:
            await self._snapshot(item, "document_vendor")
            outcome = "imported"
            revision_changed = True
        else:
            raise VendorOverlayError("runtime_unavailable")
        return {
            "outcome": outcome,
            "overlay": package.public_dict(),
            "revision_changed": revision_changed,
        }


__all__ = [
    "DocumentVendorOverlayService",
    "VendorOverlayError",
    "VendorOverlayPackage",
    "validate_vendor_archive",
]
