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

MAX_LOG_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_VISUAL_BYTES = 256 * 1024 * 1024
MAX_VISUAL_PAGES = 200
ENGINES = {"pdflatex": "pdf", "xelatex": "xelatex", "lualatex": "lualatex"}


def run(argv: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
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


def diagnostics(log: str) -> list[dict[str, object]]:
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
    if "! latex error" in log.lower() or "fatal error" in log.lower():
        match = re.search(r"(?:^|\n)([^\n:]{1,180}\.tex):(\d+):", log)
        item: dict[str, object] = {"severity": "error", "code": "compile_failed", "count": 1}
        if match:
            item["path"] = Path(match.group(1)).name
            item["line"] = int(match.group(2))
        out.append(item)
    return out


def output(argv: list[str], cwd: Path, timeout: float) -> str:
    result = run(argv, cwd, timeout)
    return result.stdout[:MAX_LOG_BYTES].decode("utf-8", "replace")


def project_tex_source(project: Path) -> str:
    """Read bounded authored TeX sources without inspecting vendor or build output."""
    excluded = {".git", ".gpthub-document", "artifacts", "vendor", "__pycache__"}
    parts: list[str] = []
    remaining = MAX_LOG_BYTES
    for path in sorted(project.rglob("*.tex")):
        relative = path.relative_to(project)
        if any(part in excluded or part.startswith(".") for part in relative.parts):
            continue
        try:
            chunk = path.read_bytes()[:remaining].decode("utf-8", "ignore")
        except OSError:
            continue
        parts.append(chunk)
        remaining -= len(chunk.encode("utf-8"))
        if remaining <= 0:
            break
    return "\n".join(parts)


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
    info = output(["pdfinfo", str(pdf)], cwd, timeout)
    fonts = output(["pdffonts", str(pdf)], cwd, timeout)
    qpdf = run(["qpdf", "--check", str(pdf)], cwd, timeout)
    pages = re.search(r"Pages:\s*(\d+)", info, re.IGNORECASE)
    size = re.search(r"Page size:\s*([\d.]+)\s+x\s+([\d.]+)\s+pts", info, re.IGNORECASE)
    meta: dict[str, object] = {
        "page_count": int(pages.group(1)) if pages else 0,
        "page_width_pt": float(size.group(1)) if size else 0.0,
        "page_height_pt": float(size.group(2)) if size else 0.0,
    }
    author = re.search(r"^Author:\s*(.*)$", info, re.IGNORECASE | re.MULTILINE)
    meta["author_present"] = bool(author and author.group(1).strip())
    audit: list[dict] = []
    if qpdf.returncode != 0:
        audit.append({"severity": "error", "code": "pdf_invalid", "count": 1})
    if "type 3" in fonts.lower():
        audit.append({"severity": "error", "code": "type3_font", "count": 1})
    return meta, audit


def manifest_audit(
    project: Path, metadata: dict[str, object], *, publication: bool
) -> list[dict[str, object]]:
    try:
        manifest = tomllib.loads((project / "document.toml").read_text("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return [{"severity": "error", "code": "manifest_invalid", "count": 1}]
    out: list[dict[str, object]] = []
    pages = int(metadata.get("page_count") or 0)
    max_pages = int(manifest.get("max_pages") or 0)
    if max_pages and pages > max_pages:
        out.append({"severity": "error", "code": "page_limit", "count": pages - max_pages})
    width = float(metadata.get("page_width_pt") or 0.0)
    height = float(metadata.get("page_height_pt") or 0.0)
    expected = {
        "a4": (595.3, 841.9),
        "letter": (612.0, 792.0),
        "slide_16_9": (453.5, 255.1),
    }.get(str(manifest.get("paper") or ""))
    if expected and (abs(width - expected[0]) > 4.0 or abs(height - expected[1]) > 4.0):
        out.append({"severity": "error", "code": "page_geometry", "count": 1})
    orientation = str(manifest.get("orientation") or "portrait")
    wrong_orientation = (orientation == "landscape" and width <= height) or (
        orientation == "portrait" and height <= width
    )
    if width and height and wrong_orientation:
        out.append({"severity": "error", "code": "page_orientation", "count": 1})
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
        entrypoint_source = entrypoint.read_text("utf-8", errors="ignore")
    except OSError:
        entrypoint_source = ""
    source = project_tex_source(project)
    if manifest.get("bibliography_required") and not re.search(
        r"\\(?:auto|paren|text|foot|super)?cite\*?(?:\[[^\]]*\])?\{", source
    ):
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
    for section in manifest.get("required_sections") or []:
        if str(section).casefold() not in source.casefold():
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


def source_bundle(project: Path, target: Path) -> None:
    excluded_dirs = {".git", ".gpthub-document", "artifacts", "__pycache__"}
    excluded_suffixes = {
        ".aux",
        ".bbl",
        ".bcf",
        ".blg",
        ".fdb_latexmk",
        ".fls",
        ".log",
        ".out",
        ".run.xml",
        ".toc",
        ".nav",
        ".snm",
        ".pdf",
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in project.rglob("*") if item.is_file()):
            relative = path.relative_to(project)
            if any(part in excluded_dirs for part in relative.parts):
                continue
            if any(path.name.endswith(suffix) for suffix in excluded_suffixes):
                continue
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2024, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def visual_bundle(pdf: Path, output_dir: Path, cwd: Path, timeout: float) -> tuple[Path, Path]:
    """Raster every page and pack deterministic, bounded visual-audit input."""

    pages_dir = output_dir / "visual-pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    rendered = run(
        ["pdftoppm", "-png", "-r", "110", str(pdf), str(pages_dir / "page")],
        cwd,
        timeout,
    )
    pages = sorted(pages_dir.glob("page-*.png"))
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
        engine_flag = f"-{ENGINES[args.engine]}"
        result = run(
            [
                "latexmk",
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
        report["diagnostics"] = diagnostics(log)
        pdf = project / f"{stem}.pdf"
        if result.returncode != 0 or not pdf.is_file():
            if not report["diagnostics"]:
                report["diagnostics"] = [
                    {"severity": "error", "code": "compile_failed", "count": 1}
                ]
            return 1
        if pdf.stat().st_size > MAX_ARTIFACT_BYTES:
            report["failure_code"] = "artifact_too_large"
            return 1
        meta, pdf_audit = pdf_metadata(pdf, project, min(30.0, args.timeout))
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
        report.update(meta)
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
