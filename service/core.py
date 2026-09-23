"""Shared lifecycle for an autonomous document-authoring sidecar."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class SidecarError(RuntimeError):
    """A bounded sidecar operation failed validation."""


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "sidecar.json"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REFERENCE = re.compile(r"^(?:S\d{3,}|ST\d{3,})$")


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SidecarError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SidecarError(f"top-level JSON must be an object: {path}")
    return payload


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def object_sha256(payload: Any) -> str:
    material = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(material).hexdigest().upper()


def tree_sha256(root: Path) -> str:
    entries = [
        f"{path.relative_to(root).as_posix()}|{sha256(path)}"
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]
    return hashlib.sha256("\n".join(entries).encode()).hexdigest().upper()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _inside(path: Path, base: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise SidecarError(f"path escapes allowed root: {path}") from exc
    return resolved


def _safe_segment(value: str) -> str:
    if not SAFE_NAME.fullmatch(value) or Path(value).name != value:
        raise SidecarError("name contains unsupported characters")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DocumentSidecar:
    def __init__(self, root: Path | str = ROOT) -> None:
        self.root = Path(root).resolve()
        self.config = load_json(self.root / "sidecar.json")
        self.registry_path = self.root / self.config["registry"]

    @property
    def registry(self) -> dict[str, Any]:
        return load_json(self.registry_path)

    def _documents(self) -> list[dict[str, Any]]:
        documents = self.registry.get("documents", [])
        return documents if isinstance(documents, list) else []

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        wanted = document_id.upper()
        return next((dict(item) for item in self._documents() if item.get("id") == wanted), None)

    def list_documents(self) -> dict[str, Any]:
        return {"items": self._documents(), "total": len(self._documents())}

    def _snapshot(self) -> dict[str, Any] | None:
        path = self.root / "data" / "research-snapshot" / "snapshot.json"
        return load_json(path) if path.is_file() else None

    def get_research_snapshot(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        if snapshot is None:
            return {"available": False, "selected_refs": []}
        return {
            "available": True,
            "meta": snapshot.get("meta", {}),
            "selected_refs": snapshot.get("selected_refs", []),
            "sources": len(snapshot.get("sources", [])),
            "resources": len(snapshot.get("resources", [])),
        }

    def _allowed_source(self, relative_path: str) -> Path:
        candidate = _inside(self.root / relative_path, self.root)
        allowed = [self.root / value for value in self.config.get("source_roots", [])]
        if not any(
            candidate == base.resolve() or base.resolve() in candidate.parents for base in allowed
        ):
            raise SidecarError("path is outside configured source roots")
        if candidate.suffix.lower() not in {".tex", ".bib", ".md", ".json"}:
            raise SidecarError("only tex, bib, md, and json source files are writable")
        return candidate

    def save_section(
        self,
        relative_path: str,
        content: str,
        expected_sha256: str | None,
        *,
        apply: bool = False,
    ) -> dict[str, Any]:
        path = self._allowed_source(relative_path)
        current = sha256(path) if path.is_file() else None
        if path.is_file() and not expected_sha256:
            raise SidecarError("expected_sha256 is required when overwriting a source")
        if expected_sha256 and current != expected_sha256.upper():
            raise SidecarError("source changed since it was read")
        new_hash = hashlib.sha256((content.rstrip("\n") + "\n").encode()).hexdigest().upper()
        result = {
            "ok": True,
            "applied": apply,
            "path": relative_path,
            "previous_sha256": current,
            "new_sha256": new_hash,
        }
        if apply:
            if self._path_is_immutable(path):
                raise SidecarError("immutable document source cannot be modified")
            self.snapshot("pre-save-section")
            atomic_write_text(path, content)
            checked = self.validate()
            if not checked["ok"]:
                raise SidecarError("post-write integrity failed: " + "; ".join(checked["errors"]))
        return result

    def _path_is_immutable(self, path: Path) -> bool:
        for document in self._documents():
            if not document.get("immutable"):
                continue
            document_root = (self.root / document["source_dir"]).resolve()
            if path == document_root or document_root in path.parents:
                return True
        return False

    def _source_files(self, document: dict[str, Any]) -> list[tuple[Path, Path]]:
        """Return bounded source files and their stable archive paths."""
        source_dir = (self.root / document["source_dir"]).resolve()
        roots = (
            [self.root / value for value in self.config.get("source_roots", [])]
            if source_dir == self.root
            else [source_dir]
        )
        collected: dict[str, tuple[Path, Path]] = {}
        for root in roots:
            if root.is_file():
                collected[root.relative_to(self.root).as_posix()] = (
                    root,
                    root.relative_to(self.root),
                )
            elif root.is_dir():
                for path in sorted(item for item in root.rglob("*") if item.is_file()):
                    relative = path.relative_to(self.root)
                    if any(
                        part in {"build", "archive", "examples", "releases", ".venv"}
                        for part in relative.parts
                    ):
                        continue
                    collected[relative.as_posix()] = (path, relative)
        return [collected[key] for key in sorted(collected)]

    def validate(self, *, profile: str = "draft", document_id: str | None = None) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        registry = self.registry
        schema_path = self.root / "data" / "document-registry.schema.json"
        if not schema_path.is_file():
            errors.append("document registry schema is missing")
        else:
            schema = load_json(schema_path)
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                errors.append("unsupported document registry schema")
            else:
                errors.extend(
                    f"registry schema: {issue.message}"
                    for issue in Draft202012Validator(schema).iter_errors(registry)
                )
        if registry.get("meta", {}).get("schema_version") != "1.0.0":
            errors.append("registry schema_version must be 1.0.0")
        documents = self._documents()
        ids = [item.get("id") for item in documents if isinstance(item, dict)]
        if len(ids) != len(set(ids)) or len(ids) != len(documents):
            errors.append("document IDs must be unique")

        snapshot = self._snapshot()
        known_refs = set(snapshot.get("selected_refs", [])) if snapshot else set()
        if snapshot:
            items = [
                *snapshot.get("sources", []),
                *snapshot.get("resources", []),
            ]
            expected_hashes = snapshot.get("item_hashes", {})
            for item in items:
                item_id = item.get("id") or item.get("resource_id")
                if expected_hashes.get(item_id) != object_sha256(item):
                    errors.append(f"research snapshot item hash mismatch: {item_id}")
        for document in documents:
            current_id = document.get("id", "<missing>")
            for field in ("id", "title", "kind", "status", "source_dir", "evidence_refs"):
                if field not in document:
                    errors.append(f"{current_id}: missing {field}")
            source_dir = self.root / str(document.get("source_dir", ""))
            if not source_dir.exists():
                errors.append(f"{current_id}: source_dir does not exist")
            refs = document.get("evidence_refs", [])
            if not isinstance(refs, list) or any(not REFERENCE.fullmatch(str(ref)) for ref in refs):
                errors.append(f"{current_id}: invalid evidence_refs")
            missing_refs = set(refs) - known_refs
            if missing_refs:
                errors.append(
                    f"{current_id}: refs absent from research snapshot: {sorted(missing_refs)}"
                )
            for trace in document.get("traceability", []):
                trace_refs = trace.get("refs", [])
                if not trace_refs or any(ref not in refs for ref in trace_refs):
                    errors.append(f"{current_id}: traceability refs must be declared evidence_refs")
                construct = trace.get("target_construct")
                if construct not in self.config.get("allowed_target_constructs", []):
                    errors.append(f"{current_id}: unknown or mixed target_construct: {construct}")
            for item in document.get("immutable_files", []):
                path = self.root / item.get("path", "")
                if not path.is_file():
                    errors.append(f"{current_id}: immutable file missing: {item.get('path')}")
                elif sha256(path) != item.get("sha256"):
                    errors.append(f"{current_id}: immutable hash mismatch: {item.get('path')}")
            expected_tree = document.get("immutable_tree_sha256")
            if expected_tree and source_dir.is_dir() and tree_sha256(source_dir) != expected_tree:
                errors.append(f"{current_id}: immutable source tree hash mismatch")

        selected = self.get_document(document_id) if document_id else None
        if document_id and selected is None:
            errors.append(f"unknown document: {document_id}")
        if selected:
            scan_files = [path for path, _ in self._source_files(selected)]
        else:
            scan_files = [
                path
                for source_root in self.config.get("source_roots", [])
                for path in (self.root / source_root).rglob("*")
                if (self.root / source_root).is_dir() and path.is_file()
            ]
        source_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in scan_files
            if path.suffix.lower() == ".tex"
        )
        placeholder_patterns = self.config.get("placeholder_patterns", [])
        placeholders = sum(
            len(re.findall(pattern, source_text)) for pattern in placeholder_patterns
        )
        if placeholders:
            message = f"{placeholders} unresolved draft placeholders"
            (errors if profile == "release" else warnings).append(message)

        cite_keys = {
            value.strip()
            for group in re.findall(r"\\(?:auto|paren|text)?cite\{([^}]+)\}", source_text)
            for value in group.split(",")
        }
        bib_keys: set[str] = set()
        for path in scan_files:
            if path.suffix.lower() == ".bib":
                bib_keys.update(re.findall(r"@\w+\{\s*([^,\s]+)", path.read_text(encoding="utf-8")))
        if cite_keys - bib_keys:
            errors.append(f"missing bibliography keys: {sorted(cite_keys - bib_keys)}")

        if profile == "release":
            approvals = registry.get("release_approvals", {})
            missing = [name for name, approved in approvals.items() if approved is not True]
            if missing:
                errors.append(f"release approvals missing: {sorted(missing)}")

        archive_errors = self._validate_archives()
        errors.extend(archive_errors)
        errors.extend(self._validate_releases())
        return {
            "ok": not errors,
            "profile": profile,
            "errors": errors,
            "warnings": warnings,
            "counts": {
                "documents": len(documents),
                "evidence_refs": len(
                    {ref for item in documents for ref in item.get("evidence_refs", [])}
                ),
                "placeholders": placeholders,
                "archive_manifests": len(list((self.root / "archive").glob("*/manifest.json"))),
            },
        }

    def _validate_archives(self) -> list[str]:
        errors: list[str] = []
        for manifest_path in sorted((self.root / "archive").glob("*/manifest.json")):
            manifest = load_json(manifest_path)
            for item in manifest.get("files", []):
                path = manifest_path.parent / item.get("path", "")
                if not path.is_file():
                    errors.append(f"archive file missing: {path}")
                elif sha256(path) != item.get("sha256"):
                    errors.append(f"archive hash mismatch: {path}")
        return errors

    def _validate_releases(self) -> list[str]:
        errors: list[str] = []
        for manifest_path in sorted((self.root / "releases").glob("*/manifest.json")):
            manifest = load_json(manifest_path)
            for item in manifest.get("files", []):
                path = manifest_path.parent / item.get("name", "")
                if not path.is_file():
                    errors.append(f"release file missing: {path}")
                elif sha256(path) != item.get("sha256"):
                    errors.append(f"release hash mismatch: {path}")
        return errors

    def status(self) -> dict[str, Any]:
        validation = self.validate()
        fingerprint_files = [self.registry_path, self.root / "sidecar.json"]
        snapshot_path = self.root / "data" / "research-snapshot" / "snapshot.json"
        if snapshot_path.is_file():
            fingerprint_files.append(snapshot_path)
        material = "|".join(sha256(path) for path in fingerprint_files)
        return {
            "name": self.config["name"],
            "version": self.config["version"],
            "fingerprint": hashlib.sha256(material.encode()).hexdigest().upper()[:16],
            "integrity": validation,
            "research_snapshot": self.get_research_snapshot(),
        }

    def snapshot(self, label: str) -> dict[str, Any]:
        label = _safe_segment(label)
        destination = (
            self.root / "archive" / (datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ") + f"-{label}")
        )
        if destination.exists():
            raise SidecarError(f"snapshot exists: {destination.name}")
        destination.mkdir(parents=True)
        entries: list[dict[str, Any]] = []
        for relative in self.config.get("snapshot_paths", []):
            source = self.root / relative
            if not source.exists():
                continue
            target = destination / relative
            if source.is_dir():
                shutil.copytree(source, target)
                files = target.rglob("*")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                files = [target]
            for path in files:
                if path.is_file():
                    entries.append(
                        {
                            "path": path.relative_to(destination).as_posix(),
                            "bytes": path.stat().st_size,
                            "sha256": sha256(path),
                        }
                    )
        manifest = {
            "snapshot_at": _now(),
            "status": "immutable_sidecar_snapshot",
            "label": label,
            "files": sorted(entries, key=lambda item: item["path"]),
        }
        atomic_write_json(destination / "manifest.json", manifest)
        return {"ok": True, "snapshot": str(destination), "files": len(entries)}

    def import_research(
        self, research_dir: Path | str, refs: list[str], *, apply: bool = False
    ) -> dict[str, Any]:
        if not refs or any(not REFERENCE.fullmatch(ref) for ref in refs):
            raise SidecarError("refs must contain SNNN/STNNN identifiers")
        data = Path(research_dir).resolve()
        if data.name != "data":
            data = data / "data"
        records = load_json(data / "records.json")
        resources = load_json(data / "ST.json")
        source_map = {item["id"]: item for item in records.get("sources", [])}
        resource_map = {
            resource["resource_id"]: resource
            for category in resources.get("categories", [])
            for subcategory in category.get("подкатегории", [])
            for resource in subcategory.get("ресурсы", [])
        }
        missing = [ref for ref in refs if ref not in source_map and ref not in resource_map]
        if missing:
            raise SidecarError(f"research refs not found: {missing}")
        evidence_files = [
            data / "records.json",
            data / "ST.json",
            data / "scientific-contract.json",
            data / "human-dataset-matrix.json",
        ]
        source_fingerprint = (
            hashlib.sha256("|".join(sha256(path) for path in evidence_files).encode())
            .hexdigest()
            .upper()[:16]
        )
        payload = {
            "meta": {
                "schema_version": "1.0.0",
                "imported_at": _now(),
                "source": "aspa-research",
                "source_fingerprint": source_fingerprint,
                "source_files": [
                    {"name": path.name, "sha256": sha256(path)} for path in evidence_files
                ],
            },
            "selected_refs": sorted(set(refs)),
            "sources": [source_map[ref] for ref in refs if ref in source_map],
            "resources": [resource_map[ref] for ref in refs if ref in resource_map],
            "scientific_contract": load_json(data / "scientific-contract.json"),
            "human_dataset_matrix": load_json(data / "human-dataset-matrix.json"),
        }
        payload["item_hashes"] = {
            (item.get("id") or item.get("resource_id")): object_sha256(item)
            for item in [*payload["sources"], *payload["resources"]]
        }
        result = {
            "ok": True,
            "applied": apply,
            "source_fingerprint": source_fingerprint,
            "selected_refs": payload["selected_refs"],
        }
        if apply:
            current = self.root / "data" / "research-snapshot" / "snapshot.json"
            if current.is_file():
                self.snapshot("pre-research-import")
            atomic_write_json(current, payload)
        return result

    def build(
        self, document_id: str, profile: str = "draft", *, apply: bool = True
    ) -> dict[str, Any]:
        if profile not in {"draft", "release"}:
            raise SidecarError("profile must be draft or release")
        document = self.get_document(document_id)
        if document is None:
            raise SidecarError(f"unknown document: {document_id}")
        validation = self.validate(profile=profile, document_id=document_id)
        if not validation["ok"]:
            return {"ok": False, "applied": False, "validation": validation}
        entry = document.get("entrypoint")
        if not entry:
            output = self.root / str(document.get("primary_output", ""))
            ok = output.is_file()
            return {
                "ok": ok,
                "applied": False,
                "immutable_artifact": True,
                "output": str(output),
                "sha256": sha256(output) if ok else None,
            }
        if not apply:
            return {"ok": True, "applied": False, "entrypoint": entry, "profile": profile}
        build_dir = self.root / "build" / document_id.lower()
        build_dir.mkdir(parents=True, exist_ok=True)
        entry_path = self.root / entry
        source_argument = entry_path.name
        xelatex = [
            "xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={build_dir}",
        ]
        if self.config.get("uses_biber") and profile == "draft":
            xelatex.extend(
                [f"-jobname={entry_path.stem}", rf"\def\ASPADraft{{1}}\input{{{source_argument}}}"]
            )
        else:
            xelatex.append(source_argument)
        commands = [xelatex]
        if self.config.get("uses_biber") and profile == "release":
            commands.extend([["biber", entry_path.stem], xelatex, xelatex])
        else:
            commands.append(xelatex)
        runs: list[dict[str, Any]] = []
        returncode = 0
        for command in commands:
            cwd = build_dir if command[0] == "biber" else entry_path.parent
            try:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    check=False,
                    timeout=120,
                )
                returncode = result.returncode
                runs.append(
                    {
                        "command": command,
                        "returncode": returncode,
                        "stdout_tail": result.stdout[-2000:],
                        "stderr_tail": result.stderr[-2000:],
                    }
                )
            except subprocess.TimeoutExpired as exc:
                returncode = 124
                runs.append({"command": command, "returncode": 124, "error": str(exc)})
            if returncode:
                break
        pdf = build_dir / f"{entry_path.stem}.pdf"
        report = {
            "ok": returncode == 0 and pdf.is_file(),
            "applied": True,
            "profile": profile,
            "document_id": document_id,
            "commands": runs,
            "returncode": returncode,
            "output": str(pdf),
            "sha256": sha256(pdf) if pdf.is_file() else None,
        }
        atomic_write_json(build_dir / "validation-report.json", report)
        return report

    def release(self, document_id: str, version: str, *, apply: bool = False) -> dict[str, Any]:
        version = _safe_segment(version)
        check = self.build(document_id, profile="release", apply=False)
        if not check["ok"]:
            return {"ok": False, "applied": False, "validation": check}
        destination = self.root / "releases" / version
        if destination.exists():
            raise SidecarError("release version already exists")
        if not apply:
            return {"ok": True, "applied": False, "destination": str(destination)}
        built = self.build(document_id, profile="release", apply=True)
        if not built["ok"]:
            return built
        destination.mkdir(parents=True)
        pdf = Path(built["output"])
        shutil.copy2(pdf, destination / pdf.name)
        report_source = self.root / "build" / document_id.lower() / "validation-report.json"
        report_name = "validation-report.json"
        shutil.copy2(report_source, destination / report_name)
        source_zip = destination / "sources.zip"
        document = self.get_document(document_id)
        assert document is not None
        with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, relative in self._source_files(document):
                archive.write(path, relative)
        manifest = {
            "version": version,
            "released_at": _now(),
            "document_id": document_id,
            "research_snapshot": self.get_research_snapshot(),
            "files": [
                {"name": pdf.name, "sha256": sha256(destination / pdf.name)},
                {"name": source_zip.name, "sha256": sha256(source_zip)},
                {"name": report_name, "sha256": sha256(destination / report_name)},
            ],
        }
        atomic_write_json(destination / "manifest.json", manifest)
        return {"ok": True, "applied": True, "destination": str(destination)}

    def package(self, document_id: str, *, apply: bool = False) -> dict[str, Any]:
        document = self.get_document(document_id)
        if document is None:
            raise SidecarError(f"unknown document: {document_id}")
        destination = self.root / "build" / f"{document_id.lower()}-sources.zip"
        if not apply:
            return {"ok": True, "applied": False, "destination": str(destination)}
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, relative in self._source_files(document):
                archive.write(path, relative)
        return {
            "ok": True,
            "applied": True,
            "destination": str(destination),
            "sha256": sha256(destination),
        }
