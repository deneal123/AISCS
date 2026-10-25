"""Check source layout, package metadata, Git hygiene and maintained navigation."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
TEMP_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".aux",
    ".log",
    ".blg",
    ".bcf",
    ".fls",
    ".out",
    ".toc",
    ".nav",
    ".snm",
    ".lof",
    ".lot",
    ".fdb_latexmk",
}
TEMP_DIRS = {
    ".venv",
    ".work",
    ".knowledge",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
}


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
    )


def archive_members(root: Path) -> set[str]:
    """Only files already bound to an immutable archive manifest get this exemption."""
    result = set()
    for path in (root / "archive").glob("*/manifest.json"):
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        for item in manifest["files"]:
            result.add((path.parent.relative_to(root) / item["path"]).as_posix())
    return result


def check(root: Path = ROOT) -> list[str]:
    errors = []
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    metadata = project["project"]
    role = metadata["name"].removeprefix("aspa-").removesuffix("-sidecar")
    required = {
        "README.md",
        "TODO.md",
        "SKILL.md",
        "pyproject.toml",
        "uv.lock",
        ".gitignore",
        ".gitattributes",
        "Makefile",
        "data",
        "docs",
        "service",
        "scripts",
        "tests",
    }
    roots = {
        "research": {"docker", "knowledge", "migrations"},
        "text": {"document"},
        "presentation": {"document"},
        "publications": {"documents", "posters"},
    }
    if role not in roots:
        return ["Unknown project role: " + role]
    required |= roots[role]
    if role == "research":
        required |= {".dockerignore", ".env.example"}
    if role != "research":
        required.add("sidecar.json")
    allowed = required | TEMP_DIRS | {"archive", "examples", ".git", ".pre-commit-config.yaml"}
    for entry in root.iterdir():
        if (
            entry.name not in allowed
            and git(root, "check-ignore", "-q", "--", entry.name).returncode
        ):
            errors.append("Unexpected repository root entry: " + entry.name)
    for name in sorted(required):
        if not (root / name).exists():
            errors.append("Missing layout entry: " + name)
    if role != "research":
        config = json.loads((root / "sidecar.json").read_text(encoding="utf-8"))
        if config["name"] != metadata["name"] or config["version"] != metadata["version"]:
            errors.append("Package and sidecar name/version differ")
        for path in config["source_roots"]:
            if not (root / path).is_dir() or not (root / path).resolve().is_relative_to(
                root.resolve()
            ):
                errors.append("Invalid source root: " + path)
    else:
        for path in root.glob("*compose*.y*ml"):
            errors.append("Docker configuration outside docker/: " + path.name)
    module = root / "service" / ("contracts.py" if role == "research" else "__init__.py")
    symbol = "SERVICE_VERSION" if role == "research" else "__version__"
    versions = {
        node.targets[0].id: node.value.value
        for node in ast.parse(module.read_text(encoding="utf-8")).body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    if versions.get(symbol) != metadata["version"]:
        errors.append("Runtime and package versions differ")
    if not metadata.get("description") or not metadata.get("urls", {}).get("Repository"):
        errors.append("Package description/repository metadata missing")
    tracked = git(root, "ls-files", "-z")
    if tracked.returncode:
        return errors + ["Cannot read tracked Git paths"]
    frozen = archive_members(root)
    for relative in filter(None, tracked.stdout.split("\0")):
        path = Path(relative)
        if relative in frozen:
            continue
        if any(part in TEMP_DIRS for part in path.parts) or path.suffix in TEMP_SUFFIXES:
            errors.append("Tracked disposable file: " + relative)
        if path.name == ".env" or path.name.startswith(".env.") and path.name != ".env.example":
            errors.append("Tracked environment credentials: " + relative)
    probes = [
        ".work/probe.json",
        ".venv/probe",
        "build/probe.pdf",
        "dist/probe.whl",
        ".env",
        "nested/.env",
        "service/__pycache__/probe.pyc",
        "document/probe.aux",
        "~$probe.docx",
    ]
    if role == "research":
        probes += [".knowledge/fulltext.pdf", "data/staging/inbox/probe.json"]
    for path in probes:
        if git(root, "check-ignore", "--no-index", "-q", "--", path).returncode:
            errors.append("Not ignored: " + path)
    for name in ["README.md", "TODO.md", "SKILL.md"]:
        text = (root / name).read_text(encoding="utf-8")
        if b"\r" in (root / name).read_bytes() or (root / name).read_bytes().startswith(
            b"\xef\xbb\xbf"
        ):
            errors.append("Expected UTF-8/LF without BOM: " + name)
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
            target = unquote(target.removeprefix("<").removesuffix(">"))
            if target.startswith(("https://", "http://", "mailto:")):
                continue
            relative = target.split("#", 1)[0]
            if relative and not (root / relative).exists():
                errors.append(f"Broken navigation in {name}: {target}")
    return sorted(set(errors))


def main() -> None:
    errors = check()
    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
