#!/usr/bin/env python3
"""Run one bounded LaTeX build and emit a sanitized JSON report.

The caller owns container isolation and output transfer. This process never
prints source, command output, file contents or arbitrary exception text.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import zipfile
from pathlib import Path

from document_page_audit import geometry_diagnostics, page_count, page_inventory
from document_source_audit import (
    SourceAuditFailure,
    active_tex,
    has_citation,
    section_titles,
)
from document_source_audit import (
    authored_source as project_tex_source,
)
from document_source_audit import authoring_manifest_audit as _authoring_manifest_audit
from font_audit import font_diagnostics
from source_identity import source_path

MAX_LOG_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_VISUAL_BYTES = 256 * 1024 * 1024
MAX_VISUAL_PAGES = 200
ENGINES = {"pdflatex": "pdf", "xelatex": "xelatex", "lualatex": "lualatex"}


def run(argv: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
    vendor_inputs = str((cwd / "vendor").resolve()) + "//:"
    return subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
        env={
            **os.environ,
            "SOURCE_DATE_EPOCH": os.environ.get("SOURCE_DATE_EPOCH", "1704067200"),
            "FORCE_SOURCE_DATE": "1",
            "max_print_line": "1000",
            # Project-local vendor classes/styles/bibliography files are reachable only
            # inside the already isolated compiler container. No host path is exposed.
            "TEXINPUTS": vendor_inputs,
            "BIBINPUTS": vendor_inputs,
            "BSTINPUTS": vendor_inputs,
        },
    )


def safe_log(path: Path) -> str:
    try:
        return path.read_bytes()[:MAX_LOG_BYTES].decode("utf-8", "replace")
    except OSError:
        return ""


def count(log: str, needle: str) -> int:
    return log.lower().count(needle.lower())


def missing_file_count(log: str) -> int:
    """Count only actual TeX file-resolution failures.

    TeX startup logs legitimately contain capability probes such as
    ``\\pdfdraftmode not found``.  Treating every ``not found`` fragment as a
    missing source/package rejects otherwise valid PDFs after compilation.
    Actual missing-file failures use one of the stable TeX error forms below.
    """

    patterns = (
        r"(?:LaTeX|Package\s+[^\r\n]+)\s+Error:\s+File\s+[`'][^\r\n]+?['`]\s+not\s+found",
        r"I\s+can't\s+find\s+file\s+[`'][^\r\n]+?['`]",
    )
    return sum(len(re.findall(pattern, log, re.IGNORECASE)) for pattern in patterns)


_COMPILER_FAILURE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "unsupported_character",
        ("unicode character", "inputenc error", "unavailable in encoding"),
    ),
    ("missing_math_delimiter", ("missing $ inserted", "math shift")),
    (
        "unbalanced_group",
        (
            "extra }",
            "runaway argument",
            "file ended while scanning",
            "end occurred inside a group",
        ),
    ),
    (
        "invalid_command_argument",
        (
            "paragraph ended before",
            "doesn't match its definition",
            "does not match its definition",
        ),
    ),
    ("undefined_control_sequence", ("undefined control sequence",)),
    ("invalid_alignment", ("misplaced \\noalign", "extra alignment tab")),
    ("invalid_dimension", ("illegal unit of measure", "missing number")),
    ("missing_file", ("not found", "i can't find file")),
)


def _compiler_failure_identity(log: str) -> tuple[str | None, int | None, str, str]:
    """Return a user-safe TeX location and a bounded compiler error code."""

    file_line = re.compile(
        r"(?m)^(?P<path>[^\r\n:]{1,512}\.tex):(?P<line>\d{1,7}):\s*(?P<message>[^\r\n]*)"
    )
    matches = list(file_line.finditer(log))
    for match in matches:
        line = int(match.group("line"))
        if not 1 <= line <= 1_000_000:
            continue
        message = match.group("message").casefold()
        if re.match(r"(?:(?:latex|package\s+\S+)\s+)?warning:", message):
            continue
        for code, needles in _COMPILER_FAILURE_PATTERNS:
            if any(needle in message for needle in needles):
                return Path(match.group("path")).name, line, code, source_path(match.group("path"))

    folded = log.casefold()
    code = next(
        (
            candidate
            for candidate, needles in _COMPILER_FAILURE_PATTERNS
            if any(needle in folded for needle in needles)
        ),
        "compile_failed",
    )
    return None, None, code, ""


def _compiler_failure_location(log: str) -> tuple[str | None, int | None, str]:
    """Compatibility projection of display location; never infers block ownership."""
    path, line, code, _source_path = _compiler_failure_identity(log)
    return path, line, code


def _append_compiler_failure(out: list[dict[str, object]], log: str) -> list[dict[str, object]]:
    path, line, code, relative = _compiler_failure_identity(log)
    existing = next(
        (item for item in out if item.get("severity") == "error" and item.get("code") == code),
        None,
    )
    if existing is None:
        existing = {"severity": "error", "code": code, "count": 1}
        out.append(existing)
    if path is not None:
        existing["path"] = path
    if line is not None:
        existing["line"] = line
    existing["source_path"] = relative
    return out


def diagnostics(log: str, *, compilation_failed: bool = False) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for severity, code, needles in (
        ("error", "undefined_reference", ("undefined references", "reference `")),
        ("error", "undefined_citation", ("undefined citations", "citation `")),
        ("error", "multiply_defined", ("multiply defined",)),
        ("error", "font_unavailable", ("fontspec error", "font cannot be found")),
        (
            "error",
            "missing_glyph",
            ("missing character: there is no", "missing character: no glyph"),
        ),
        ("error", "undefined_control_sequence", ("undefined control sequence",)),
        ("error", "invalid_alignment", ("misplaced \\noalign", "extra alignment tab")),
        ("error", "invalid_dimension", ("illegal unit of measure", "missing number")),
        ("warning", "overfull_box", ("overfull \\hbox", "overfull \\vbox")),
        ("warning", "underfull_box", ("underfull \\hbox", "underfull \\vbox")),
    ):
        amount = sum(count(log, item) for item in needles)
        if amount:
            out.append({"severity": severity, "code": code, "count": amount})
    missing = missing_file_count(log)
    if missing:
        out.append({"severity": "error", "code": "missing_file", "count": missing})
    if compilation_failed or "! latex error" in log.lower() or "fatal error" in log.lower():
        _append_compiler_failure(out, log)
    return out


def output(argv: list[str], cwd: Path, timeout: float) -> str:
    result = run(argv, cwd, timeout)
    return result.stdout[:MAX_LOG_BYTES].decode("utf-8", "replace")


def authoring_manifest_audit(
    project: Path, profile_id: str, publication: bool = True
) -> list[dict[str, object]]:
    """Validate renderer-owned semantic provenance without returning authored text."""

    return _authoring_manifest_audit(project, profile_id, publication)


def lint_diagnostics(entrypoint: Path, project: Path, timeout: float) -> list[dict[str, object]]:
    result = run(
        ["chktex", "-q", "-n1", "-n8", "-n13", "-n46", entrypoint.name],
        project,
        min(30.0, timeout),
    )
    warnings = sum(1 for line in result.stdout.splitlines() if line.strip())
    if warnings:
        return [{"severity": "warning", "code": "latex_lint", "count": min(warnings, 999)}]
    return []


def pdf_metadata(pdf: Path, cwd: Path, timeout: float) -> tuple[dict[str, object], list[dict]]:
    info_result = run(["pdfinfo", str(pdf)], cwd, timeout)
    info = info_result.stdout[:MAX_LOG_BYTES].decode("utf-8", "replace")
    fonts = run(["pdffonts", str(pdf)], cwd, timeout)
    qpdf = run(["qpdf", "--check", str(pdf)], cwd, timeout)
    meta: dict[str, object] = {
        "page_count": 0,
        "page_width_pt": 0.0,
        "page_height_pt": 0.0,
    }
    author = re.search(r"^Author:\s*(.*)$", info, re.IGNORECASE | re.MULTILINE)
    meta["author_present"] = bool(author and author.group(1).strip())
    audit: list[dict] = []
    try:
        if info_result.returncode != 0 or len(info_result.stdout) > MAX_LOG_BYTES:
            raise ValueError("pdf_invalid")
        count = page_count(info)
        detailed = run(["pdfinfo", "-f", "1", "-l", str(count), str(pdf)], cwd, timeout)
        if detailed.returncode != 0 or len(detailed.stdout) > MAX_LOG_BYTES:
            raise ValueError("pdf_invalid")
        inventory = page_inventory(detailed.stdout.decode("utf-8", "strict"), count)
        meta.update(
            page_count=count,
            page_width_pt=inventory[0][0],
            page_height_pt=inventory[0][1],
            _page_geometry=inventory,
        )
    except (ValueError, UnicodeError):
        audit.append({"severity": "error", "code": "pdf_invalid", "count": 1})
    if qpdf.returncode != 0:
        audit.append({"severity": "error", "code": "pdf_invalid", "count": 1})
    font_report = fonts.stdout[:MAX_LOG_BYTES].decode("utf-8", "replace")
    font_errors = (
        font_diagnostics(font_report)
        if fonts.returncode == 0 and len(fonts.stdout) <= MAX_LOG_BYTES
        else (("font_unavailable", 1),)
    )
    audit.extend({"severity": "error", "code": code, "count": count} for code, count in font_errors)
    return meta, audit


def manifest_audit(
    project: Path, metadata: dict[str, object], *, publication: bool
) -> list[dict[str, object]]:
    try:
        manifest = tomllib.loads((project / "document.toml").read_text("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return [{"severity": "error", "code": "manifest_invalid", "count": 1}]
    effective_path = project / ".gpthub-effective-profile.json"
    if effective_path.is_file():
        try:
            effective = json.loads(effective_path.read_text("utf-8"))
            base_limit = int(manifest.get("max_pages") or 0)
            effective_limit = effective.get("max_pages")
            allowed_keys = {
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
            valid = (
                isinstance(effective, dict)
                and set(effective) == allowed_keys
                and effective.get("schema_version") == 1
                and effective.get("base_profile_id") == manifest.get("profile_id")
                and effective.get("base_profile_version") == manifest.get("profile_version")
                and effective.get("paper") == manifest.get("paper")
                and effective.get("orientation") == manifest.get("orientation")
                and effective.get("export_allowed") is False
                and isinstance(effective.get("vendor_package_id"), str)
                and re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", effective["vendor_package_id"])
                and isinstance(effective.get("documentclass"), str)
                and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", effective["documentclass"])
                and isinstance(effective.get("bibliography_style"), str)
                and (
                    not effective["bibliography_style"]
                    or re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", effective["bibliography_style"])
                )
                and isinstance(effective.get("content_contract"), str)
                and re.fullmatch(r"[a-z][a-z0-9_.-]{1,63}", effective["content_contract"])
                and isinstance(effective_limit, int)
                and not isinstance(effective_limit, bool)
                and effective_limit >= 0
                and (not base_limit or 0 < effective_limit <= base_limit)
                and isinstance(effective.get("required_sections"), list)
                and len(effective["required_sections"]) <= 32
                and all(
                    isinstance(item, str) and 1 <= len(item) <= 120
                    for item in effective["required_sections"]
                )
            )
        except (OSError, UnicodeError, ValueError, TypeError):
            valid = False
            effective = {}
        if not valid:
            return [{"severity": "error", "code": "vendor_profile_invalid", "count": 1}]
        manifest = {
            **manifest,
            "documentclass": effective["documentclass"],
            "max_pages": effective_limit,
            "required_sections": list(
                dict.fromkeys(
                    [
                        *(str(item) for item in manifest.get("required_sections") or []),
                        *(str(item) for item in effective["required_sections"]),
                    ]
                )
            ),
            "source_export": "forbidden",
        }
    out: list[dict[str, object]] = []
    pages = int(metadata.get("page_count") or 0)
    max_pages = int(manifest.get("max_pages") or 0)
    if max_pages and pages > max_pages:
        out.append({"severity": "error", "code": "page_limit", "count": pages - max_pages})
    width = float(metadata.get("page_width_pt") or 0.0)
    height = float(metadata.get("page_height_pt") or 0.0)
    inventory = metadata.get("_page_geometry", ((width, height, 0),))
    out.extend(
        {"severity": "error", "code": code, "count": count}
        for code, count in geometry_diagnostics(
            inventory,
            str(manifest.get("paper") or ""),
            str(manifest.get("orientation") or "portrait"),
        )
    )
    if manifest.get("bibliography_required"):
        bibliography = project / "bibliography" / "references.bib"
        bibliography_text = (
            bibliography.read_text("utf-8", errors="ignore") if bibliography.is_file() else ""
        )
        if not re.search(r"@[A-Za-z]+\s*\{", bibliography_text):
            out.append(
                {
                    "severity": "error" if publication else "warning",
                    "code": "bibliography_missing",
                    "count": 1,
                }
            )
    if manifest.get("anonymize") and metadata.get("author_present"):
        out.append({"severity": "error", "code": "anonymization_failed", "count": 1})
    entrypoint = project / str(manifest.get("entrypoint") or "main.tex")
    try:
        entrypoint_source = active_tex(entrypoint.read_text("utf-8"))
        source = project_tex_source(project, str(manifest.get("entrypoint") or "main.tex"))
    except (OSError, UnicodeError, SourceAuditFailure):
        return [{"severity": "error", "code": "authoring_invalid", "count": 1}]
    out.extend(
        authoring_manifest_audit(project, str(manifest.get("profile_id") or ""), publication)
    )
    if manifest.get("bibliography_required") and not has_citation(source):
        out.append(
            {
                "severity": "error" if publication else "warning",
                "code": "citation_missing",
                "count": 1,
            }
        )
    documentclass = re.search(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}", entrypoint_source)
    if not documentclass or documentclass.group(1) != manifest.get("documentclass"):
        out.append({"severity": "error", "code": "documentclass_mismatch", "count": 1})
    headings = section_titles(source)
    abstract_environment = bool(re.search(r"\\begin\s*\{abstract\}", source, re.IGNORECASE))
    bibliography_environment = bool(
        re.search(r"\\(?:printbibliography|bibliography\s*\{)", source, re.IGNORECASE)
    )
    for section in manifest.get("required_sections") or []:
        normalized_section = " ".join(str(section).split()).casefold()
        semantic_environment_present = (
            normalized_section in {"abstract", "аннотация"} and abstract_environment
        ) or (
            normalized_section in {"bibliography", "references", "литература", "список литературы"}
            and bibliography_environment
        )
        if normalized_section not in headings and not semantic_environment_present:
            out.append({"severity": "error", "code": "required_section", "count": 1})
    if re.search(r"\{\{[A-Z][A-Z0-9_]{2,}\}\}", source) or "\\DocumentPlaceholder{" in source:
        out.append(
            {
                "severity": "error" if publication else "warning",
                "code": "unresolved_placeholder",
                "count": 1,
            }
        )
    vendor_files = (
        [
            path
            for path in (project / "vendor").rglob("*")
            if path.is_file() and path.name != "license.toml"
        ]
        if (project / "vendor").is_dir()
        else []
    )
    if publication and vendor_files and manifest.get("source_export") != "forbidden":
        license_path = project / "vendor" / "license.toml"
        try:
            license_manifest = tomllib.loads(license_path.read_text("utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            license_manifest = {}
        if license_manifest.get("distributable") is not True:
            out.append({"severity": "error", "code": "vendor_license_missing", "count": 1})
    return out


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def block_pages(project: Path, entrypoint: Path) -> list[dict[str, object]]:
    """Read renderer-owned labels from the final aux file without exposing source text."""

    aux = project / f"{entrypoint.stem}.aux"
    try:
        source = aux.read_text("utf-8", errors="ignore")
    except OSError:
        return []
    found: list[dict[str, object]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r"\\newlabel\{gpthub:block:([a-z][a-z0-9_-]{2,63})\}"
        r"\{\{.*?\}\{(\d{1,4})\}",
    )
    for block_id, raw_page in pattern.findall(source):
        page = int(raw_page)
        if block_id in seen or not 1 <= page <= MAX_VISUAL_PAGES:
            continue
        seen.add(block_id)
        found.append({"block_id": block_id, "page": page})
        if len(found) >= 120:
            break
    return found


def source_bundle(project: Path, target: Path) -> None:
    # Project-local vendor kits are executable, untrusted and non-redistributable by
    # default. Trusted global profiles are baked into the runtime, never copied from
    # this directory.
    excluded_dirs = {".git", ".gpthub-document", "artifacts", "vendor", "__pycache__"}
    # Export source by an explicit allowlist.  TeX engines keep adding new
    # intermediate formats (for example XeLaTeX's ``.xdv``), so a denylist can
    # silently turn a source archive into a compiler-work archive.  The list
    # below contains authored text, profile support files and static assets
    # needed to reproduce a build; final PDF and every engine by-product stay
    # outside the Library bundle.
    source_suffixes = {
        ".bbx",
        ".bib",
        ".bst",
        ".cbx",
        ".cfg",
        ".clo",
        ".cls",
        ".csv",
        ".def",
        ".eps",
        ".jpeg",
        ".jpg",
        ".json",
        ".lbx",
        ".md",
        ".png",
        ".sty",
        ".svg",
        ".tex",
        ".toml",
        ".tsv",
        ".txt",
        ".yaml",
        ".yml",
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in project.rglob("*") if item.is_file()):
            relative = path.relative_to(project)
            if any(part in excluded_dirs for part in relative.parts):
                continue
            if path.is_symlink() or path.suffix.lower() not in source_suffixes:
                continue
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2024, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def visual_bundle(pdf: Path, output_dir: Path, cwd: Path, timeout: float) -> tuple[Path, Path]:
    """Raster every page and pack deterministic, bounded visual-audit input."""

    inventory = run(["pdfinfo", str(pdf)], cwd, timeout)
    if inventory.returncode != 0 or len(inventory.stdout) > MAX_LOG_BYTES:
        raise ValueError("visual bundle unavailable")
    try:
        expected_pages = page_count(inventory.stdout.decode("utf-8", "strict"))
    except (ValueError, UnicodeError):
        raise ValueError("visual bundle unavailable") from None
    if expected_pages > MAX_VISUAL_PAGES:
        raise ValueError("visual bundle unavailable")
    pages_dir = output_dir / "visual-pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    rendered = run(
        ["pdftoppm", "-png", "-r", "110", str(pdf), str(pages_dir / "page")],
        cwd,
        timeout,
    )
    numbered = []
    for path in pages_dir.glob("page-*.png"):
        match = re.fullmatch(r"page-([0-9]{1,5})\.png", path.name)
        if not match or path.is_symlink() or not path.is_file():
            raise ValueError("visual bundle unavailable")
        numbered.append((int(match[1]), path))
    if len(numbered) != expected_pages or {number for number, _ in numbered} != set(
        range(1, expected_pages + 1)
    ):
        raise ValueError("visual bundle unavailable")
    pages = [path for _, path in sorted(numbered)]
    total = sum(path.stat().st_size for path in pages)
    if (
        rendered.returncode != 0
        or not pages
        or len(pages) > MAX_VISUAL_PAGES
        or total > MAX_VISUAL_BYTES
    ):
        raise ValueError("visual bundle unavailable")
    preview = output_dir / "preview.png"
    shutil.copy2(pages[0], preview)
    target = output_dir / "visual-pages.tar"
    with tarfile.open(target, "w") as archive:
        for index, path in enumerate(pages, start=1):
            payload = path.read_bytes()
            info = tarfile.TarInfo(f"page-{index:03d}.png")
            info.size = len(payload)
            info.mode = 0o444
            info.mtime = 1_704_067_200
            archive.addfile(info, io.BytesIO(payload))
    if target.stat().st_size > MAX_VISUAL_BYTES:
        target.unlink(missing_ok=True)
        raise ValueError("visual bundle unavailable")
    return target, preview


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--engine", choices=sorted(ENGINES), required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", default="/output")
    parser.add_argument("--publication", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    project = Path(args.project).resolve()
    entrypoint = (project / args.entrypoint).resolve()
    out_dir = Path(args.output).resolve()
    report: dict[str, object] = {"status": "failed", "failure_code": "compile_failed"}
    try:
        if project not in entrypoint.parents or entrypoint.suffix.lower() != ".tex":
            report["failure_code"] = "invalid_project"
            return 2
        out_dir.mkdir(parents=True, exist_ok=True)
        # Imported auxiliary state must not stand in for this build's dependency
        # evidence. Force an engine pass with a fresh recorder inventory.
        entrypoint.with_suffix(".fls").unlink(missing_ok=True)
        engine_flag = f"-{ENGINES[args.engine]}"
        result = run(
            [
                "latexmk",
                "-g",
                "-recorder",
                engine_flag,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "-no-shell-escape",
                entrypoint.name,
            ],
            project,
            args.timeout,
        )
        stem = entrypoint.stem
        log = safe_log(project / f"{stem}.log")
        pdf = project / f"{stem}.pdf"
        report["diagnostics"] = diagnostics(
            log,
            compilation_failed=result.returncode != 0 or not pdf.is_file(),
        )
        if result.returncode != 0 or not pdf.is_file():
            return 1
        if pdf.stat().st_size > MAX_ARTIFACT_BYTES:
            report["failure_code"] = "artifact_too_large"
            return 1
        meta, pdf_audit = pdf_metadata(pdf, project, min(30.0, args.timeout))
        if args.publication and int(meta.get("page_count") or 0) > MAX_VISUAL_PAGES:
            pdf_audit.append({"severity": "error", "code": "page_limit", "count": 1})
        report["diagnostics"] = [
            *report["diagnostics"],
            *lint_diagnostics(entrypoint, project, args.timeout),
            *pdf_audit,
            *manifest_audit(project, meta, publication=args.publication),
        ]
        if any(item.get("severity") == "error" for item in report["diagnostics"]):
            report["failure_code"] = "audit_failed"
            return 1
        target = out_dir / "document.pdf"
        shutil.copy2(pdf, target)
        visual_archive: Path | None = None
        preview = out_dir / "preview.png"
        if args.publication:
            try:
                visual_archive, preview = visual_bundle(
                    pdf, out_dir, project, min(90.0, args.timeout)
                )
            except ValueError:
                report["failure_code"] = "visual_render_failed"
                report["diagnostics"].append(
                    {"severity": "error", "code": "visual_render_failed", "count": 1}
                )
                return 1
        else:
            preview_result = run(
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-singlefile",
                    "-png",
                    "-r",
                    "96",
                    str(pdf),
                    str(preview.with_suffix("")),
                ],
                project,
                min(30.0, args.timeout),
            )
            if preview_result.returncode != 0 or not preview.is_file():
                report["diagnostics"].append(
                    {"severity": "warning", "code": "preview_unavailable", "count": 1}
                )
        bundle = out_dir / "source.zip"
        source_bundle(project, bundle)
        if bundle.stat().st_size > MAX_ARTIFACT_BYTES:
            bundle.unlink(missing_ok=True)
        report.update({key: value for key, value in meta.items() if not key.startswith("_")})
        report.update(
            {
                "status": "ready",
                "failure_code": "",
                "artifact": {
                    "filename": "document.pdf",
                    "size": target.stat().st_size,
                    "sha256": sha256(target),
                },
                "source_bundle": (
                    {
                        "filename": "source.zip",
                        "size": bundle.stat().st_size,
                        "sha256": sha256(bundle),
                    }
                    if bundle.is_file()
                    else None
                ),
                "preview": (
                    {"size": preview.stat().st_size, "sha256": sha256(preview)}
                    if preview.is_file()
                    else None
                ),
                "visual_bundle": (
                    {
                        "size": visual_archive.stat().st_size,
                        "sha256": sha256(visual_archive),
                        "page_count": int(meta.get("page_count") or 0),
                    }
                    if visual_archive is not None and visual_archive.is_file()
                    else None
                ),
                "block_pages": block_pages(project, entrypoint),
            }
        )
        return 0
    except subprocess.TimeoutExpired:
        report["failure_code"] = "build_timeout"
        return 124
    except Exception:
        report["failure_code"] = "internal"
        return 1
    finally:
        report["duration_ms"] = int((time.monotonic() - started) * 1000)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=True, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            pass
        print(
            json.dumps({"status": report.get("status"), "failure_code": report.get("failure_code")})
        )


if __name__ == "__main__":
    sys.exit(main())
