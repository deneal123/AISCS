#!/usr/bin/env python3
"""Build a real Cyrillic PDF in the isolated Document Forge image.

The smoke keeps source and output in disposable container tmpfs. It prints only
bounded build facts and always removes the compiler container.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import secrets
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_ROOT = ROOT / "workspace" / "service" / "domain" / "documents" / "profile_data"
_FAILURE_CODES = frozenset(
    {
        "profile_invalid",
        "profile_engine_invalid",
        "artifact_missing",
        "container_create",
        "container_start",
        "source_copy",
        "compile_failed",
        "artifact_stream",
        "pdf_invalid",
        "digest_mismatch",
        "source_bundle_invalid",
        "audit_failed",
        "cleanup_unconfirmed",
        "process_timeout",
        "process_unavailable",
        "smoke_failed",
    }
)


def _bounded_failure(error: BaseException) -> str:
    code = error.args[0] if len(error.args) == 1 else None
    return code if isinstance(code, str) and code in _FAILURE_CODES else "smoke_failed"


def _run(
    *args: str, input_bytes: bytes | None = None, timeout: float = 90.0
) -> subprocess.CompletedProcess[bytes]:
    if not 0 < timeout <= 600:
        raise RuntimeError("process_unavailable")
    try:
        return subprocess.run(
            args,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("process_timeout") from None
    except OSError:
        raise RuntimeError("process_unavailable") from None


def _owned_container(name: str) -> str | None:
    """Prove exact-name ownership before any use or destructive command."""
    if not re.fullmatch(r"gpthub-document-smoke-[a-f0-9]{12}", name):
        raise RuntimeError("cleanup_unconfirmed")
    try:
        listing = _run(
            "docker",
            "ps",
            "-a",
            "--no-trunc",
            "--filter",
            f"name=^/{name}$",
            "--format",
            "{{.ID}}",
            timeout=15,
        )
        if listing.returncode or len(listing.stdout) > 256:
            raise ValueError()
        ids = listing.stdout.decode("ascii", "strict").split()
        if not ids:
            return None
        if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]{64}", ids[0]):
            raise ValueError()
        projection = (
            '{"id":{{json .Id}},"name":{{json .Name}},'
            '"owner":{{json (index .Config.Labels "gpthub.document.smoke")}}}'
        )
        inspected = _run(
            "docker", "inspect", "--format", projection, ids[0], timeout=15
        )
        if inspected.returncode or len(inspected.stdout) > 4096:
            raise ValueError()
        value = json.loads(inspected.stdout)
        if value != {"id": ids[0], "name": "/" + name, "owner": name}:
            raise ValueError()
        return ids[0]
    except (OSError, RuntimeError, ValueError, UnicodeError):
        raise RuntimeError("cleanup_unconfirmed") from None


def _cleanup_container(name: str) -> None:
    identity = _owned_container(name)
    if identity is None:
        return
    try:
        _run("docker", "rm", "-f", identity, timeout=15)
    except RuntimeError:
        # A lost acknowledgement is not proof of either failure or removal.
        pass
    if _owned_container(name) is not None:
        raise RuntimeError("cleanup_unconfirmed")


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return (
            "["
            + ", ".join(json.dumps(item, ensure_ascii=False) for item in value)
            + "]"
        )
    return json.dumps(str(value), ensure_ascii=False)


def _project_manifest(profile: dict[str, object], *, publication: bool) -> str:
    profile_id = str(profile["profile_id"])
    kind = str(profile["kind"])
    content_contract = str(profile.get("content_contract") or f"{kind}-v1")
    mode = "camera_ready" if publication else "draft"
    values: dict[str, object] = {
        "schema_version": 1,
        "kind": kind,
        "profile_id": profile_id,
        "profile_version": int(profile["version"]),
        "locale": str(profile.get("locale") or "en-US"),
        "entrypoint": str(profile["entrypoint"]),
        "engine": str(profile["engine"]),
        "documentclass": str(profile["documentclass"]),
        "paper": str(profile["paper"]),
        "orientation": str(profile["orientation"]),
        "mode": mode,
        "bibliography_backend": str(profile.get("bibliography_backend") or "none"),
        "bibliography_required": bool(profile.get("bibliography_required")),
        "required_sections": list(profile.get("required_sections") or []),
        "locked_fields": list(profile.get("locked_fields") or []),
        "allowed_overrides": list(profile.get("allowed_overrides") or []),
        "anonymize": bool(
            publication and profile.get("anonymize_supported") and mode == "submission"
        ),
        "max_pages": int(profile.get("max_pages") or 0),
        "source_export": str(profile.get("source_export") or "forbidden"),
        "content_contract": content_contract,
    }
    return "".join(f"{key} = {_toml_value(value)}\n" for key, value in values.items())


def _source_archive(
    profile_id: str, *, publication: bool
) -> tuple[bytes, dict[str, object]]:
    profile_dir = PROFILE_ROOT / profile_id
    try:
        profile = tomllib.loads(
            (profile_dir / "profile.toml").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError("profile_invalid") from exc
    if str(profile.get("profile_id") or "") != profile_id:
        raise RuntimeError("profile_invalid")
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        manifest = _project_manifest(profile, publication=publication).encode("utf-8")
        manifest_info = tarfile.TarInfo("document.toml")
        manifest_info.size = len(manifest)
        manifest_info.mode = 0o444
        manifest_info.mtime = 1_704_067_200
        archive.addfile(manifest_info, io.BytesIO(manifest))
        for base in (PROFILE_ROOT / "_shared", profile_dir):
            for path in sorted(item for item in base.rglob("*") if item.is_file()):
                if path.name == "profile.toml":
                    continue
                encoded = path.read_bytes()
                name = path.relative_to(base).as_posix()
                if name == "main.tex" and profile_id == "generic_document":
                    template = encoded.decode("utf-8")
                    prefix, marker, _body = template.partition("\\begin{document}")
                    if not marker or "\\end{document}" not in template:
                        raise RuntimeError("profile_invalid")
                    encoded = (prefix + marker + "\nтест\n\\end{document}\n").encode()
                info = tarfile.TarInfo(name)
                info.size = len(encoded)
                info.mode = 0o444
                info.mtime = 1_704_067_200
                archive.addfile(info, io.BytesIO(encoded))
    return payload.getvalue(), profile


def _extract_pdf(payload: bytes) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        member = next(
            (
                item
                for item in archive.getmembers()
                if item.name.rstrip("/").endswith("document.pdf")
            ),
            None,
        )
        if member is None:
            raise RuntimeError("artifact_missing")
        stream = archive.extractfile(member)
        if stream is None:
            raise RuntimeError("artifact_missing")
        return stream.read()


def _source_bundle_is_clean(payload: bytes) -> bool:
    """Prove that publication exports authored inputs, never engine state."""

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = {item.filename for item in archive.infolist() if not item.is_dir()}
    except (OSError, ValueError, zipfile.BadZipFile):
        return False
    forbidden_suffixes = {
        ".aux",
        ".bbl",
        ".bcf",
        ".blg",
        ".dvi",
        ".fdb_latexmk",
        ".fls",
        ".log",
        ".nav",
        ".out",
        ".pdf",
        ".run.xml",
        ".snm",
        ".synctex",
        ".toc",
        ".xdv",
    }
    return (
        {"document.toml", "main.tex"}.issubset(names)
        and not any(name.startswith("vendor/") for name in names)
        and not any(
            any(name.endswith(suffix) for suffix in forbidden_suffixes)
            for name in names
        )
    )


def _smoke_profile(
    image: str, profile_id: str, *, publication: bool
) -> tuple[int, int]:
    name = f"gpthub-document-smoke-{secrets.token_hex(6)}"
    container_id = ""
    create_attempted = False
    try:
        source_archive, profile = _source_archive(profile_id, publication=publication)
        engine = str(profile.get("engine") or "")
        if engine not in {"pdflatex", "xelatex", "lualatex"}:
            raise RuntimeError("profile_engine_invalid")
        create_attempted = True
        created = _run(
            "docker",
            "create",
            "--name",
            name,
            "--label",
            f"gpthub.document.smoke={name}",
            "--pull",
            "never",
            "--memory",
            "1536m",
            "--memory-swap",
            "1536m",
            "--cpus",
            "2",
            "--pids-limit",
            "384",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--tmpfs",
            "/job:rw,exec,size=33554432,mode=1777",
            "--tmpfs",
            "/output:rw,size=335544320,mode=1777",
            "--tmpfs",
            "/tmp:rw,exec,size=268435456,mode=1777",
            "--entrypoint",
            "sleep",
            image,
            "infinity",
        )
        if created.returncode:
            raise RuntimeError("container_create")
        container_id = created.stdout.decode("ascii", "ignore").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            raise RuntimeError("container_create")
        if _owned_container(name) != container_id:
            raise RuntimeError("container_create")
        if _run("docker", "start", container_id).returncode:
            raise RuntimeError("container_start")
        copied = _run(
            "docker",
            "exec",
            "-i",
            container_id,
            "tar",
            "-C",
            "/job",
            "-xf",
            "-",
            input_bytes=source_archive,
        )
        if copied.returncode:
            raise RuntimeError("source_copy")
        built = _run(
            "docker",
            "exec",
            container_id,
            "python3",
            "/opt/document-runtime/runner.py",
            "--project",
            "/job",
            "--entrypoint",
            "main.tex",
            "--engine",
            engine,
            *(["--publication"] if publication else []),
            timeout=420,
        )
        if built.returncode:
            raise RuntimeError("compile_failed")
        report_result = _run(
            "docker", "exec", container_id, "cat", "/output/report.json"
        )
        report = (
            json.loads(report_result.stdout[:262_144])
            if not report_result.returncode
            else {}
        )
        exported = _run(
            "docker",
            "exec",
            container_id,
            "tar",
            "-C",
            "/output",
            "-cf",
            "-",
            "document.pdf",
        )
        if exported.returncode:
            raise RuntimeError("artifact_stream")
        pdf = _extract_pdf(exported.stdout)
        if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-4096:]:
            raise RuntimeError("pdf_invalid")
        expected = str((report.get("artifact") or {}).get("sha256") or "")
        if expected != hashlib.sha256(pdf).hexdigest():
            raise RuntimeError("digest_mismatch")
        if publication:
            bundle = _run("docker", "exec", container_id, "cat", "/output/source.zip")
            if bundle.returncode or not _source_bundle_is_clean(bundle.stdout):
                raise RuntimeError("source_bundle_invalid")
        pages = int(report.get("page_count") or 0)
        if report.get("status") != "ready" or pages < 1:
            raise RuntimeError("audit_failed")
        return pages, len(pdf)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(_bounded_failure(exc)) from None
    finally:
        if create_attempted:
            _cleanup_container(name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="gpthub-document-runtime:latest")
    parser.add_argument(
        "--all-profiles",
        action="store_true",
        help="Compile every trusted profile as an isolated preview build.",
    )
    args = parser.parse_args()
    profile_ids = (
        sorted(
            path.name
            for path in PROFILE_ROOT.iterdir()
            if path.is_dir() and not path.name.startswith("_")
        )
        if args.all_profiles
        else ["generic_document"]
    )
    total_pages = 0
    total_size = 0
    try:
        for profile_id in profile_ids:
            pages, size = _smoke_profile(
                args.image,
                profile_id,
                publication=not args.all_profiles or profile_id == "generic_document",
            )
            total_pages += pages
            total_size += size
        print(
            "document-runtime-smoke: "
            f"status=ready profiles={len(profile_ids)} pages={total_pages} size={total_size}"
        )
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"document-runtime-smoke: status=failed code={_bounded_failure(exc)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
