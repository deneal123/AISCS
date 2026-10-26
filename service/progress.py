"""Weekly progress snapshot for PRES-002: read-only counts from the dissertation workspace.

Every number on the progress slides comes from this module. It reads the canonical
registries of the neighbouring projects, never writes outside this sidecar and records
the SHA-256 of each source, so the slides can be traced back to the exact files.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .core import DocumentSidecar, SidecarError, atomic_write_json, atomic_write_text, load_json
from .core import sha256 as file_sha256

STATUS_TEX = "document/progress/generated/status.tex"
SNAPSHOT_JSON = "data/progress-snapshot.json"
COMPONENTS = {
    "research": "research",
    "text": "materials/text",
    "publications": "materials/publications",
    "presentation": "materials/presentation",
}
TODO_ITEM = re.compile(r"^\s*- \[( |x)\]\s+(?:\*\*([A-Z]+-\d+)\b)?")
RELEASE = re.compile(r"(?:release|evidence base)\s+v?(\d+\.\d+\.\d+)", re.IGNORECASE)
IPR_PLAN = re.compile(r"(\d+)\s+журнальных\s+и\s+(\d+)\s+конференционных")
TEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
SIM_STATUS = {
    "reproduced": "Воспроизведено",
    "partial": "Частично",
    "blocked": "Заблокировано",
    "pending": "Ожидает проверки",
}
SIM_GROUPS = {
    "connectome-preparation": "Подготовка и анализ коннектома",
    "connectome-analysis": "Подготовка и анализ коннектома",
    "neural": "Нейродинамика",
    "neural-fitting": "Нейродинамика",
    "visual-neural": "Нейродинамика",
    "browser-neural": "Нейродинамика",
    "motor-cpg": "Нейродинамика",
    "embodied": "Тело и среда",
    "embodied-game": "Тело и среда",
    "body-environment": "Тело и среда",
    "body-environment-compatibility": "Тело и среда",
}
SIM_OTHER = "Методы сравнения и авторские анализы"
PUBLICATION_STATUS = {
    "submitted": "Направлена",
    "accepted": "Принята",
    "published": "Опубликована",
    "draft": "Черновик",
}


def tex(value: Any) -> str:
    return "".join(TEX_SPECIAL.get(char, char) for char in str(value))


def ru_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def compress_codes(codes: list[str]) -> str:
    """``EXP-01, EXP-02, EXP-03, CON-05`` → ``EXP-01–03, CON-05``; numbers keep their width."""
    groups: dict[str, list[str]] = defaultdict(list)
    for code in codes:
        prefix, number = code.rsplit("-", 1)
        groups[prefix].append(number)
    parts = []
    for prefix, numbers in groups.items():
        numbers = sorted(set(numbers), key=int)
        runs: list[list[str]] = []
        for number in numbers:
            if runs and int(number) == int(runs[-1][-1]) + 1:
                runs[-1].append(number)
            else:
                runs.append([number])
        rendered = [
            f"{run[0]}–{run[-1]}" if len(run) > 2 else ", ".join(run) for run in runs
        ]
        parts.append(f"{prefix}-" + ", ".join(rendered))
    return ", ".join(parts)


class _Sources:
    """Workspace reader that records the hash and Git state of every file it reads."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.files: dict[str, str] = {}
        self._dirty: dict[Path, set[str]] = {}

    def path(self, relative: str, *, required: bool = True) -> Path | None:
        path = self.workspace / relative
        if not path.is_file():
            if required:
                raise SidecarError(f"progress source is missing: {relative}")
            return None
        self.files[relative] = file_sha256(path)
        return path

    def json(self, relative: str, *, required: bool = True) -> dict[str, Any] | None:
        path = self.path(relative, required=required)
        return load_json(path) if path else None

    def text(self, relative: str) -> str:
        path = self.path(relative)
        assert path is not None
        return path.read_text(encoding="utf-8")

    def uncommitted(self, repositories: dict[str, Path], own: Path) -> list[str]:
        """Sources that differ from the committed state of their own repository.

        Files of this sidecar (``own``) are skipped: the snapshot is committed with them.
        """
        dirty = []
        for relative in sorted(self.files):
            absolute = (self.workspace / relative).resolve()
            if own in absolute.parents:
                continue
            repo = max(
                (path for path in repositories.values() if path in absolute.parents),
                key=lambda path: len(path.parts),
            )
            if repo not in self._dirty:
                status = _git(
                    repo, "status", "--porcelain", "--untracked-files=all",
                    "--ignore-submodules=all",
                )
                self._dirty[repo] = {line[3:].strip('"') for line in status.splitlines()}
            if absolute.relative_to(repo).as_posix() in self._dirty[repo]:
                dirty.append(relative)
        return dirty


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SidecarError(f"git is unavailable for {repo}: {exc}") from exc
    if result.returncode:
        raise SidecarError(f"git {' '.join(args[:2])} failed in {repo}: {result.stderr.strip()}")
    return result.stdout


def _todo(text: str) -> dict[str, Any]:
    done = opened = 0
    open_codes: list[str] = []
    for line in text.splitlines():
        match = TODO_ITEM.match(line)
        if not match:
            continue
        if match.group(1) == "x":
            done += 1
        else:
            opened += 1
            if match.group(2):
                open_codes.append(match.group(2))
    return {"done": done, "open": opened, "total": done + opened, "open_codes": open_codes}


def _version(sources: _Sources, component: str) -> str:
    if component == "research":
        return tomllib.loads(sources.text("research/pyproject.toml"))["project"]["version"]
    return sources.json(f"{COMPONENTS[component]}/sidecar.json")["version"]


def _research(sources: _Sources) -> dict[str, Any]:
    records = sources.json("research/data/records.json")["sources"]
    status = Counter((item.get("validation") or {}).get("status") for item in records)
    clusters = sources.json("research/data/clusters.json")
    catalogue = sources.json("research/data/ST.json")
    novelty = sources.json("research/data/research/novelty-landscape.json")
    disposition = novelty["meta"].get("operational_disposition", {})
    concept = sources.json("research/data/research/dissertation-concept.json")
    return {
        "version": _version(sources, "research"),
        "sources": len(records),
        "validation": dict(sorted(status.items())),
        "aliases": len(sources.json("research/data/aliases.json")["aliases"]),
        "clusters": len(clusters["clusters"]),
        "retired_clusters": len(clusters.get("retired_clusters", [])),
        "resources": sum(
            len(sub["ресурсы"]) for cat in catalogue["categories"] for sub in cat["подкатегории"]
        ),
        "gate": concept["meta"]["gate"],
        "novelty_variants": len(novelty["variants"]),
        "novelty_ranking": novelty["meta"].get("ranking_policy"),
        "novelty_stop": disposition.get("status"),
        "saturation": disposition.get("saturation"),
        "prior_art": disposition.get("prior_art_outcome_preserved"),
        "tasks": len(concept["tasks"]),
        "todo": _todo(sources.text("research/TODO.md")),
    }


def _knowledge(sources: _Sources) -> dict[str, Any]:
    entries = sources.json("research/knowledge/corpus-manifest.json")["entries"]
    corpus = Counter(entry.get("status") for entry in entries)
    evaluation = sources.json("research/knowledge/evaluation-results.json")
    active = sources.json("research/.knowledge/active.json", required=False) or {}
    return {
        "generation": sources.json("research/knowledge/snapshot.json")["generation"],
        "corpus": dict(sorted(corpus.items())),
        "nodes": active.get("nodes"),
        "edges": active.get("edges"),
        "vectors": active.get("vectors"),
        "search_cases": evaluation["cases"],
        "search_hits": evaluation["hits"],
    }


def _library(sources: _Sources) -> dict[str, Any]:
    catalog = sources.json("research/knowledge/library/catalog.json")["books"]
    evaluation = sources.json("research/knowledge/library/evaluation-results.json")
    active = sources.json("research/.knowledge/library/active.json", required=False) or {}
    surnames: Counter = Counter()
    for book in catalog:
        surnames[book["authors"][0].split()[0]] += 1
    return {
        "generation": sources.json("research/knowledge/library/snapshot.json")["generation"],
        "books": len(catalog),
        "full_text": sum(1 for book in catalog if book["completeness"] == "full_text"),
        "authors": [f"{name} ({count})" if count > 1 else name for name, count in surnames.items()],
        "chunks": active.get("chunks"),
        "search_cases": evaluation["cases"],
        "search_hits": evaluation["hits"],
    }


def _simulations(sources: _Sources) -> dict[str, Any]:
    candidates = sources.json("simulations/data/registry.json")["candidates"]
    assessment = sources.json("simulations/data/assessment.json")["candidates"]
    by_status: dict[str, list[str]] = defaultdict(list)
    groups: dict[str, Counter] = defaultdict(Counter)
    for item in candidates:
        status = (item.get("evaluation") or {}).get("status", "pending")
        by_status[status].append(item["id"])
        groups[SIM_GROUPS.get(item.get("role"), SIM_OTHER)][status] += 1
    passed = {
        item["id"]
        for item in assessment
        if any(c["id"] == "visuals" and c["status"] == "passed" for c in item["checks"])
    }
    return {
        "total": len(candidates),
        "by_status": {key: sorted(value) for key, value in sorted(by_status.items())},
        "groups": {key: dict(value) for key, value in sorted(groups.items())},
        "visuals": len(passed),
        "biological_validation": sum(1 for item in assessment if item.get("biological_validation")),
        "human_ecap_operator": sum(1 for item in assessment if item.get("human_ecap_operator")),
    }


def _text(sources: _Sources) -> dict[str, Any]:
    chapters = []
    root = sources.workspace / "materials/text/document/chapters"
    for path in sorted(root.glob("*.tex")):
        source = sources.text(path.relative_to(sources.workspace).as_posix())
        body = re.sub(r"(?m)(?<!\\)%.*$", "", source)
        plain = re.sub(r"\\[A-Za-z]+\*?", " ", body)
        number = int(path.name.split("-", 1)[0])
        chapters.append(
            {
                "file": path.name,
                "label": "Введение" if number == 0 else f"Глава {number}",
                "words": len(re.findall(r"[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z-]*", plain)),
                "sections": len(re.findall(r"\\section\*?\{", body)),
                "pending": len(re.findall(r"\\ResultPending\b", body)),
            }
        )
    bibliography = sources.text("materials/text/document/backmatter/references.bib")
    return {
        "version": _version(sources, "text"),
        "chapters": chapters,
        "bibliography": len(re.findall(r"(?m)^@\w+\{", bibliography)),
        "todo": _todo(sources.text("materials/text/TODO.md")),
    }


def _publications(sources: _Sources) -> dict[str, Any]:
    registry = sources.json("materials/publications/data/publications.json")
    todo_text = sources.text("materials/publications/TODO.md")
    plan = IPR_PLAN.search(todo_text)
    items = []
    for document in registry["documents"]:
        if document.get("kind") == "template":
            continue
        venue = str(document.get("venue") or "")
        short = re.search(r"\(([^()]+)\)\s*$", venue)
        items.append(
            {
                "id": document["id"],
                "venue": short.group(1) if short else venue,
                "status": document.get("status"),
                "due": document.get("planned_manuscript_ready") or document.get("deadline"),
            }
        )
    return {
        "version": _version(sources, "publications"),
        "documents": items,
        "ipr_plan": {"journal": int(plan.group(1)), "conference": int(plan.group(2))}
        if plan
        else None,
        "todo": _todo(todo_text),
    }


def _presentation(sources: _Sources, sidecar: DocumentSidecar) -> dict[str, Any]:
    base = COMPONENTS["presentation"]
    registry = sources.json(f"{base}/data/presentation.json")
    decks = []
    for document in registry["documents"]:
        for path, relative in sidecar._source_files(document):
            if path.suffix.lower() == ".tex" and relative.as_posix() != STATUS_TEX:
                sources.path(f"{base}/{relative.as_posix()}")
        decks.append(
            {
                "id": document["id"],
                "slides": sidecar.slide_count(document),
                "max_slides": document.get("max_slides"),
            }
        )
    return {
        "version": _version(sources, "presentation"),
        "decks": decks,
        "todo": _todo(sources.text(f"{base}/TODO.md")),
    }


def _history(workspace: Path, since: date, as_of: date) -> dict[str, Any]:
    window = [f"--since={since.isoformat()} 00:00", f"--until={as_of.isoformat()} 23:59:59"]
    releases = []
    commits = {}
    for component, relative in COMPONENTS.items():
        repo = workspace / relative
        log = _git(repo, "log", "--date=short", "--format=%ad%x09%s", f"--until={as_of} 23:59:59")
        seen = set()
        for line in reversed(log.splitlines()):
            day, _, subject = line.partition("\t")
            match = RELEASE.search(subject)
            if match and match.group(1) not in seen:
                seen.add(match.group(1))
                releases.append({"date": day, "component": component, "version": match.group(1)})
        commits[component] = len(_git(repo, "log", "--format=%h", *window).split())
    commits["simulations"] = len(
        _git(workspace, "log", "--format=%h", *window, "--", "simulations/data").split()
    )
    first = _git(workspace, "log", "--reverse", "--date=short", "--format=%ad").split()
    return {
        "first_commit": first[0] if first else None,
        "releases": sorted(releases, key=lambda item: (item["date"], item["component"])),
        "week_commits": commits,
    }


def collect(
    sidecar: DocumentSidecar,
    workspace: Path | str | None = None,
    *,
    since_days: int = 7,
    as_of: date | None = None,
) -> dict[str, Any]:
    if since_days < 1:
        raise SidecarError("since must be at least one day")
    root = Path(workspace).resolve() if workspace else sidecar.root.parents[1]
    if not (root / "research" / "data" / "records.json").is_file() or not (
        root / COMPONENTS["presentation"]
    ).is_dir():
        raise SidecarError(
            f"dissertation workspace not found at {root}; pass --workspace <superproject root>"
        )
    as_of = as_of or date.today()
    since = as_of - timedelta(days=since_days - 1)
    sources = _Sources(root)
    payload: dict[str, Any] = {
        "meta": {
            "schema_version": "1.0.0",
            "generated_by": "presentationctl progress-snapshot",
            "as_of": as_of.isoformat(),
            "since": since.isoformat(),
            "since_days": since_days,
        },
        "research": _research(sources),
        "knowledge": _knowledge(sources),
        "library": _library(sources),
        "simulations": _simulations(sources),
        "text": _text(sources),
        "publications": _publications(sources),
        "presentation": _presentation(sources, sidecar),
        "history": _history(root, since, as_of),
    }
    repositories = {name: (root / path).resolve() for name, path in COMPONENTS.items()}
    repositories["workspace"] = root.resolve()
    payload["repositories"] = {
        name: _git(path, "rev-parse", "--short", "HEAD").strip()
        for name, path in sorted(repositories.items())
    }
    payload["uncommitted_sources"] = sources.uncommitted(repositories, sidecar.root.resolve())
    payload["sources"] = [
        {"path": path, "sha256": digest} for path, digest in sorted(sources.files.items())
    ]
    return payload


def _rows(rows: list[list[Any]]) -> str:
    return "\n".join(" & ".join(str(cell) for cell in row) + r" \\\hline" for row in rows)


def _count(value: Any) -> str:
    return "—" if value is None else str(value)


def _week_rows(payload: dict[str, Any]) -> list[list[str]]:
    since = payload["meta"]["since"]
    labels = {
        "research": "Исследовательская база",
        "text": "Текст диссертации",
        "publications": "Публикации",
        "presentation": "Презентации",
        "simulations": "Симуляторы",
    }
    versions = {
        "research": payload["research"]["version"],
        "text": payload["text"]["version"],
        "publications": payload["publications"]["version"],
        "presentation": payload["presentation"]["version"],
    }
    released: dict[str, list[str]] = defaultdict(list)
    for item in payload["history"]["releases"]:
        if item["date"] >= since:
            released[item["component"]].append(item["version"])
    return [
        [
            labels[key],
            tex(versions.get(key, "—")),
            str(payload["history"]["week_commits"][key]),
            tex(", ".join(released.get(key, [])) or "—"),
        ]
        for key in labels
    ]


def _timeline_rows(payload: dict[str, Any]) -> list[list[str]]:
    releases = payload["history"]["releases"]
    if not releases:
        return []
    as_of = date.fromisoformat(payload["meta"]["as_of"])
    start = date.fromisoformat(releases[0]["date"])
    week = start - timedelta(days=start.weekday())
    rows = []
    while week <= as_of:
        end = week + timedelta(days=6)
        cells = [f"{week:%d.%m}–{end:%d.%m}"]
        first, last = week.isoformat(), end.isoformat()
        for component in COMPONENTS:
            versions = [
                item["version"]
                for item in releases
                if item["component"] == component and first <= item["date"] <= last
            ]
            cells.append(tex(", ".join(versions)) or "—")
        rows.append(cells)
        week += timedelta(days=7)
    return rows


def render(payload: dict[str, Any]) -> str:
    research, knowledge, library = payload["research"], payload["knowledge"], payload["library"]
    simulations, text, publications = (
        payload["simulations"],
        payload["text"],
        payload["publications"],
    )
    presentation = payload["presentation"]
    as_of = date.fromisoformat(payload["meta"]["as_of"])
    since = date.fromisoformat(payload["meta"]["since"])
    validation = research["validation"]
    corpus = knowledge["corpus"]
    defence = next((deck for deck in presentation["decks"] if deck["max_slides"]), None)
    plan = publications["ipr_plan"] or {}
    uncommitted = sorted(
        {
            next((name for name, path in COMPONENTS.items() if item.startswith(path + "/")), None)
            or item.split("/", 1)[0]
            for item in payload["uncommitted_sources"]
        }
    )
    first_commit = payload["history"]["first_commit"]
    values = {
        "AsOf": ru_date(as_of),
        "Since": ru_date(since),
        "FirstCommit": ru_date(date.fromisoformat(first_commit)) if first_commit else "—",
        "Uncommitted": tex(", ".join(uncommitted)) if uncommitted else "нет",
        "WeekCommits": sum(payload["history"]["week_commits"].values()),
        "ReleaseCount": len(payload["history"]["releases"]),
        "Sources": research["sources"],
        "VerifiedPrimary": validation.get("verified_primary", 0),
        "PartiallyVerified": validation.get("partially_verified", 0),
        "VerifiedMetadata": validation.get("verified_metadata", 0),
        "Rejected": validation.get("rejected", 0),
        "Aliases": research["aliases"],
        "Clusters": research["clusters"],
        "RetiredClusters": research["retired_clusters"],
        "Resources": research["resources"],
        "Gate": tex(research["gate"]),
        "NoveltyVariants": research["novelty_variants"],
        "NoveltyStop": tex(research["novelty_stop"] or "—"),
        "Saturation": "достигнута" if research["saturation"] else "не достигнута",
        "PriorArt": "только частичные аналоги"
        if research["prior_art"] == "partial_analogues_only"
        else tex(research["prior_art"] or "—"),
        "ResearchDone": research["todo"]["done"],
        "ResearchTotal": research["todo"]["total"],
        "CorpusAvailable": corpus.get("available", 0),
        "CorpusMissing": corpus.get("missing", 0),
        "CorpusRejected": corpus.get("rejected", 0),
        "CorpusOcr": corpus.get("needs_ocr", 0),
        "GraphNodes": _count(knowledge["nodes"]),
        "GraphEdges": _count(knowledge["edges"]),
        "Vectors": _count(knowledge["vectors"]),
        "SearchHits": knowledge["search_hits"],
        "SearchCases": knowledge["search_cases"],
        "LibraryBooks": library["books"],
        "LibraryFullText": library["full_text"],
        "LibraryChunks": _count(library["chunks"]),
        "LibraryHits": library["search_hits"],
        "LibraryCases": library["search_cases"],
        "LibraryAuthors": tex(", ".join(library["authors"])),
        "SimTotal": simulations["total"],
        "SimVisuals": simulations["visuals"],
        "SimBiological": simulations["biological_validation"],
        "SimEcap": simulations["human_ecap_operator"],
        "TextVersion": tex(text["version"]),
        "BibEntries": text["bibliography"],
        "IprJournal": _count(plan.get("journal")),
        "IprConference": _count(plan.get("conference")),
        "IprTotal": _count(sum(plan.values()) if plan else None),
        "DefenceSlides": _count(defence and defence["slides"]),
        "DefenceLimit": _count(defence and defence["max_slides"]),
        "VersionResearch": tex(research["version"]),
        "VersionText": tex(text["version"]),
        "VersionPublications": tex(publications["version"]),
        "VersionPresentation": tex(presentation["version"]),
        "KnowledgeGeneration": tex(knowledge["generation"]),
        "LibraryGeneration": tex(library["generation"]),
    }
    tables = {
        "WeekRows": _week_rows(payload),
        "TimelineRows": _timeline_rows(payload),
        "SimStatusRows": [
            [SIM_STATUS.get(status, tex(status)), len(ids), compress_codes(ids)]
            for status, ids in sorted(
                simulations["by_status"].items(),
                key=lambda item: list(SIM_STATUS).index(item[0]) if item[0] in SIM_STATUS else 99,
            )
        ],
        "SimGroupRows": [
            [
                tex(group),
                sum(counts.values()),
                counts.get("reproduced", 0),
                counts.get("partial", 0),
                counts.get("blocked", 0) + counts.get("pending", 0),
            ]
            for group, counts in simulations["groups"].items()
        ],
        "ChapterRows": [
            [
                chapter["label"],
                chapter["words"],
                chapter["pending"],
                "Текст подготовлен"
                if not chapter["pending"]
                else "Структура, ожидаются результаты",
            ]
            for chapter in text["chapters"]
        ],
        "PublicationRows": [
            [
                tex(item["id"]),
                tex(item["venue"]),
                PUBLICATION_STATUS.get(item["status"], tex(item["status"])),
                tex(".".join(reversed(str(item["due"]).split("-")))) if item["due"] else "—",
            ]
            for item in publications["documents"]
        ],
        "OpenRows": [
            [label, f"{todo['open']} из {todo['total']}", compress_codes(todo["open_codes"]) or "—"]
            for label, todo in (
                ("Исследовательская база", research["todo"]),
                ("Текст диссертации", text["todo"]),
                ("Публикации", publications["todo"]),
                ("Презентации", presentation["todo"]),
            )
        ],
    }
    lines = [
        "% Generated by `presentationctl progress-snapshot --apply`; do not edit by hand.",
        f"% As of {as_of.isoformat()}; sources and hashes: {SNAPSHOT_JSON}.",
    ]
    lines += [rf"\newcommand{{\Prog{name}}}{{{value}}}" for name, value in values.items()]
    for name, rows in tables.items():
        lines.append(rf"\newcommand{{\Prog{name}}}{{%")
        lines.append(_rows(rows) + "}")
    return "\n".join(lines) + "\n"


def progress_snapshot(
    sidecar: DocumentSidecar,
    workspace: Path | str | None = None,
    *,
    since_days: int = 7,
    as_of: date | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    payload = collect(sidecar, workspace, since_days=since_days, as_of=as_of)
    status = render(payload)
    result = {
        "ok": True,
        "applied": apply,
        "as_of": payload["meta"]["as_of"],
        "outputs": [STATUS_TEX, SNAPSHOT_JSON],
        "sources": len(payload["sources"]),
        "uncommitted_sources": payload["uncommitted_sources"],
    }
    if apply:
        atomic_write_text(sidecar.root / STATUS_TEX, status)
        atomic_write_json(sidecar.root / SNAPSHOT_JSON, payload)
    return result
