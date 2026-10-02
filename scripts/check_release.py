"""Independent inventory, digest, link and curation-bundle check."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

from service.data_layout import DATA_PATHS, current_data_files, data_path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MANIFEST = data_path(DATA, "release-manifest.json")
SCOPES = ("relevance-3", "relevance-4", "relevance-5", "st-resources")
CONSOLIDATED = {
    "src07-version-recheck-audit.json": (
        "src07-code-repository-recheck-2026-09-25.json",
        "src07-crossref-retry-2026-09-25.json",
        "src07-crossref-sweep-2026-09-25.json",
        "src07-relevance5-publisher-batch-2026-09-25.json",
        "src07-s099-uspto-primary-recheck-2026-09-25.json",
        "src07-s148-citation-resolution-2026-09-25.json",
        "src07-s227-wacv-recheck-2026-09-25.json",
        "src07-s231-primary-recheck-2026-09-25.json",
        "src07-three-owner-pages-review-2026-09-25.json",
        "src07-three-source-recovery-2026-09-25.json",
        "s272-identity-exclusion-2026-09-25.json",
    ),
    "ns15-russian-prior-art-audit.json": ("ns15-rsl-abstract-access-recheck-2026-09-25.json",),
    "search-protocol.json": ("ns14-six-trial-extension-2026-09-25.json",),
    "pa04-citation-audit-2026-09-25.json": (
        "pa04-five-primary-analogue-audit-2026-09-25.json",
        "pa04-frequency-rat-citation-audit-2026-09-25.json",
    ),
}
LEGACY_NAMES = {name for names in CONSOLIDATED.values() for name in names}
PROVENANCE = DATA / "provenance" / "source-checks"
LINK = re.compile(r"(?<!!)\]\(([^)\s]+)\)")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def current_files() -> list[Path]:
    files = [
        ROOT / "TODO.md",
        ROOT / "README.md",
        ROOT / "SKILL.md",
        *current_data_files(DATA),
        DATA / "README.md",
    ]
    files += list((DATA / "curation").rglob("*.json"))
    files += list((ROOT / "docs").rglob("*.md"))
    files += [p for p in (ROOT / "knowledge").rglob("*") if p.suffix in {".md", ".json", ".jsonl"}]
    return sorted(
        p
        for p in files
        if p.is_file()
        and p != MANIFEST
        and "batches" not in p.parts
        and not (p.parent == DATA and p.name in LEGACY_NAMES)
    )


def inventory() -> dict[str, str]:
    return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in current_files()}


def aggregate(files: dict[str, str]) -> str:
    return digest("".join(f"{name}\0{files[name]}\n" for name in sorted(files)).encode())


def check_line_endings() -> list[str]:
    return [
        f"{path.relative_to(ROOT)}: current release text must use LF line endings"
        for path in current_files()
        if b"\r\n" in path.read_bytes()
    ]


def todo_progress() -> dict[str, int]:
    text = (ROOT / "TODO.md").read_text(encoding="utf-8")
    items = re.findall(r"(?m)^- \[([ x])\] \*\*[A-Z]+-\d{2}\.", text)
    return {"closed": items.count("x"), "total": len(items)}


def check_bundles() -> list[str]:
    errors: list[str] = []
    log = json.loads((data_path(DATA, "validation-log.json")).read_text(encoding="utf-8"))["meta"]
    expected = set(log["applied_batches"]) | set(log["applied_resource_batches"])
    found: set[str] = set()
    for scope in SCOPES:
        base = DATA / "curation" / scope
        bundle = json.loads((base / "applied-batches.json").read_text(encoding="utf-8"))
        entries = bundle["entries"]
        if len(entries) != bundle["entry_count"] or set(bundle["id_index"].values()) != set(
            entries
        ):
            errors.append(f"{scope}: bundle index differs from entries")
        for name, entry in entries.items():
            raw = entry["raw_json"].encode("utf-8")
            if digest(raw) != entry["sha256"]:
                errors.append(f"{scope}/{name}: original digest mismatch")
            payload = json.loads(raw)
            batch_id = payload["meta"]["batch_id"]
            if entry["batch_id"] != batch_id or bundle["id_index"].get(batch_id) != name:
                errors.append(f"{scope}/{name}: batch ID mismatch")
            found.add(batch_id)
            legacy = DATA / "provenance" / "applied-batches" / scope / name
            if not legacy.is_file():
                errors.append(f"{scope}/{name}: frozen batch original is missing")
            elif digest(legacy.read_bytes()) != entry["sha256"]:
                errors.append(f"{scope}/{name}: frozen original differs from bundle")
            if (base / "batches" / name).exists():
                errors.append(f"{scope}/{name}: duplicate live batch reappeared")
        queue = json.loads((base / "queue.json").read_text(encoding="utf-8"))
        for item in queue["batches"]:
            name = bundle["id_index"].get(item["batch_id"])
            if name is None or item["path"] != f"curation/{scope}/applied-batches.json#{name}":
                errors.append(f"{scope}: queue locator invalid for {item['batch_id']}")
    if found != expected:
        missing = sorted(expected - found)
        extra = sorted(found - expected)
        errors.append(f"applied batch IDs differ: missing={missing}, extra={extra}")
    return errors


def check_consolidated() -> list[str]:
    errors: list[str] = []
    for target, names in CONSOLIDATED.items():
        destination = json.loads(data_path(DATA, target).read_text(encoding="utf-8"))
        checks = destination.get("consolidated_checks", {})
        if set(checks) != set(names):
            errors.append(f"{target}: consolidated check set differs")
        for name in names:
            entry = checks.get(name)
            if entry is None:
                continue
            legacy = PROVENANCE / name
            if legacy.is_file():
                raw = legacy.read_bytes()
                if digest(raw) != entry["source_sha256"] or json.loads(raw) != entry["payload"]:
                    errors.append(f"{name}: legacy file differs from consolidated audit")
            else:
                errors.append(f"{name}: frozen source check is missing")
            if (DATA / name).exists():
                errors.append(f"{name}: duplicate top-level source check reappeared")
    return errors


def check_layout() -> list[str]:
    errors: list[str] = []
    indexed, _ = markdown_targets((DATA / "README.md").read_text(encoding="utf-8"))
    indexed_names = {target for target in indexed if not target.startswith("../")}
    expected_current = {DATA / relative for relative in DATA_PATHS.values()}
    expected_originals: set[Path] = set()
    current_curation = {
        DATA / "curation/cluster-assignments/github-fly-resources-2026-09-23.json",
        DATA / "curation/relevance-5/discovery/registry-search.json",
    }
    for scope in SCOPES:
        base = DATA / "curation" / scope
        current_curation.update({base / "applied-batches.json", base / "queue.json"})
        bundle = json.loads((base / "applied-batches.json").read_text(encoding="utf-8"))
        expected_originals.update(
            DATA / "provenance/applied-batches" / scope / name for name in bundle["entries"]
        )
    for path in DATA.rglob("*"):
        if not path.is_file():
            continue
        if path.is_symlink():
            errors.append(f"symlink in data: {path.relative_to(ROOT)}")
            continue
        parts = path.relative_to(DATA).parts
        if parts[0] == "archive":
            continue
        if parts[0] == "staging":
            if parts in {
                ("staging", "README.md"),
                ("staging", "source-record.template.json"),
                ("staging", "inbox", ".gitkeep"),
            }:
                continue
            if len(parts) == 3 and parts[1] == "inbox" and path.suffix == ".json":
                candidate = json.loads(path.read_text(encoding="utf-8"))
                records = json.loads(data_path(DATA, "records.json").read_text(encoding="utf-8"))[
                    "sources"
                ]
                if candidate in records:
                    errors.append(
                        f"published candidate duplicate in staging: {path.relative_to(ROOT)}"
                    )
                continue
            errors.append(f"unexpected staging artifact: {path.relative_to(ROOT)}")
            continue
        if parts[0] == "provenance":
            if len(parts) == 3 and parts[1] == "source-checks" and parts[2] in LEGACY_NAMES:
                continue
            if path in expected_originals:
                continue
            errors.append(f"unexpected provenance file: {path.relative_to(ROOT)}")
            continue
        if path == DATA / "README.md":
            continue
        if path in expected_current:
            if path.relative_to(DATA).as_posix() not in indexed_names:
                errors.append(f"unindexed current-data file: {path.relative_to(ROOT)}")
            continue
        if parts[0] == "curation" and "batches" in parts:
            errors.append(f"unbundled current-data batch: {path.relative_to(ROOT)}")
            continue
        if path in current_curation:
            continue
        errors.append(f"unexpected current-data file: {path.relative_to(ROOT)}")
    for path in expected_current:
        if not path.is_file():
            errors.append(f"missing current-data file: {path.relative_to(ROOT)}")
    return errors


def check_corpus_summaries() -> list[str]:
    """Recount current summaries independently; dated historical sections are excluded."""

    def read(name: str) -> dict:
        return json.loads((data_path(DATA, name)).read_text(encoding="utf-8"))

    sources = read("records.json")["sources"]
    aliases = read("aliases.json")["aliases"]
    clusters = read("clusters.json")
    resources = read("ST.json")
    audit = read("audit-report.json")
    log = read("validation-log.json")["meta"]
    statuses = dict(Counter(item["validation"]["status"] for item in sources))
    errors = []
    corpus = {
        "canonical_sources": len(sources),
        "aliases": len(aliases),
        "active_clusters": len(clusters["clusters"]),
        "retired_clusters": len(clusters["retired_clusters"]),
        "resources": sum(
            len(s["ресурсы"]) for c in resources["categories"] for s in c["подкатегории"]
        ),
        "validation_statuses": statuses,
        "unverified": statuses.get("unverified", 0),
        "pending_screening": sum(
            item["validation"]["screening_status"] == "pending" for item in sources
        ),
        "reported_spdx_licenses": resources["meta"]["reported_software_licenses"],
    }
    by_relevance = {}
    for level in sorted({item["релевантность"] for item in sources}):
        subset = [item for item in sources if item["релевантность"] == level]
        by_relevance[str(level)] = {
            "canonical_count": len(subset),
            "status_counts": dict(Counter(item["validation"]["status"] for item in subset)),
        }
    curation = {
        "canonical_records": len(sources),
        "aliases": len(aliases),
        "validation_status_counts": statuses,
        "unresolved_count": sum(statuses.get(key, 0) for key in ("unverified", "pending")),
        "by_relevance": by_relevance,
        "relevance_5": by_relevance.get("5", {"canonical_count": 0, "status_counts": {}}),
        "applied_batches": log["applied_batches"],
    }
    for section, expected in (("current_corpus", corpus), ("current_curation", curation)):
        for key, value in expected.items():
            if audit[section].get(key) != value:
                errors.append(f"audit-report.json: {section}.{key} differs from canonical data")
    if curation["unresolved_count"] == 0 and log["status"] != "all_source_validation_complete":
        errors.append(
            "validation-log.json: completed bibliographic review has a stale workflow status"
        )
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    closed = set(re.findall(r"(?m)^- \[x\] \*\*([A-Z]+-\d{2})\.\*\*", todo))
    for gate in audit["remaining_gates"]:
        for task_id in set(re.findall(r"\b[A-Z]+-\d{2}\b", gate)) & closed:
            errors.append(f"audit-report.json: remaining_gates still contains closed {task_id}")
    return errors


def check_provenance_references() -> list[str]:
    errors: list[str] = []

    def walk(value: object, location: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key != "consolidated_checks":
                    walk(child, f"{location}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{location}[{index}]")
        elif isinstance(value, str):
            for name in LEGACY_NAMES:
                if name in value and f"provenance/source-checks/{name}" not in value:
                    errors.append(f"{location}: stale source-check path {name}")

    for path in current_data_files(DATA):
        if path != MANIFEST:
            walk(json.loads(path.read_text(encoding="utf-8")), path.name)
    return errors


def markdown_anchors(text: str) -> set[str]:
    """Resolve heading and explicit HTML anchors, including repeated headings."""
    anchors = set(re.findall(r"<a\s+(?:id|name)=[\"\']([^\"\']+)[\"\']", text))
    fence: str | None = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
            continue
        if fence is not None:
            continue
        heading = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading is None:
            continue
        base = re.sub(r"[^\w\- ]", "", heading[1].lower()).replace(" ", "-")
        anchor = base
        suffix = 0
        while anchor in anchors:
            suffix += 1
            anchor = f"{base}-{suffix}"
        anchors.add(anchor)
    return anchors


def check_todo_ledger() -> list[str]:
    expected = {
        f"{prefix}-{index:02}"
        for prefix, count in (
            ("SRC", 8),
            ("RES", 5),
            ("EVD", 5),
            ("PA", 8),
            ("NOV", 5),
            ("EXP", 5),
            ("CON", 5),
            ("REL", 2),
        )
        for index in range(1, count + 1)
    }
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    ids = re.findall(r"(?m)^- \[[ x]\] \*\*([A-Z]+-\d{2})\.\*\*", todo)
    errors = []
    if len(ids) != len(expected) or set(ids) != expected:
        errors.append("TODO: task IDs must contain each of the 43 expected IDs once")
    ledger = ROOT / "docs" / "audits" / "todo-decision-ledger.md"
    if not ledger.is_file():
        return errors + ["TODO: decision ledger is missing"]
    sections = re.findall(r"(?m)^## ([A-Z]+-\d{2})\s*$", ledger.read_text(encoding="utf-8"))
    if len(sections) != len(expected) or set(sections) != expected:
        errors.append("TODO ledger: task sections must contain each expected ID once")
    for task_id in expected:
        locator = f"docs/audits/todo-decision-ledger.md#{task_id.lower()}"
        if f"]({locator})" not in todo:
            errors.append(f"TODO: decision ledger link is missing for {task_id}")
    return errors


def markdown_targets(text: str) -> tuple[list[str], list[str]]:
    """Include reusable reference links so deduplicated locators remain checked."""
    targets = [match[1] for match in LINK.finditer(text)]
    definitions: dict[str, str] = {}
    errors = []
    for match in re.finditer(r"(?m)^ {0,3}\[([^\]]+)\]:\s*(\S+)", text):
        label = match[1].strip().casefold()
        if label in definitions:
            errors.append(f"duplicate reference label {match[1]}")
        definitions[label] = match[2].strip("<>")
    for match in re.finditer(r"(?<!!)\[[^\]\n]+\]\[([^\]\n]+)\]", text):
        label = match[1].strip().casefold()
        if label not in definitions:
            errors.append(f"undefined reference label {match[1]}")
        else:
            targets.append(definitions[label])
    return targets, errors


def check_current_state() -> list[str]:
    errors = []

    def read_json(name: str) -> dict:
        return json.loads((data_path(DATA, name)).read_text(encoding="utf-8"))

    sources = read_json("records.json")["sources"]
    aliases = read_json("aliases.json")["aliases"]
    clusters = read_json("clusters.json")
    report = (ROOT / "docs/final-validation-report.md").read_text(encoding="utf-8")
    count_checks = (
        (r"содержит (\d+) карточек и (\d+) алиас", (len(sources), len(aliases))),
        (
            r"— (\d+) активных и (\d+) исторических",
            (
                len(clusters["clusters"]),
                len(clusters["retired_clusters"]),
            ),
        ),
    )
    for pattern, expected in count_checks:
        match = re.search(pattern, report)
        if match is None or tuple(map(int, match.groups())) != expected:
            errors.append("current report: corpus counts differ from canonical data")
    progress = todo_progress()
    if f"**{progress['closed']}/{progress['total']}**" not in report:
        errors.append("current report: TODO progress differs")
    search = read_json("search-protocol.json")
    novelty = read_json("novelty-landscape.json")
    accepted = search["pa_saturation_log_2026_10_01"]["pa08_author_bounded_cutoff_2026_10_01"]
    cutoff = accepted["date"]
    if search["meta"]["cutoff"] != cutoff or novelty["meta"]["cutoff"] != cutoff:
        errors.append("current cutoffs differ from author-accepted bounded search")
    if accepted["search_saturation"] is not False:
        errors.append("accepted bounded search must not imply saturation")
    if accepted["decision"] != "bounded_search_accepted_at_cutoff":
        errors.append("author bounded-search decision is missing")
    if search["meta"]["status"] != "bounded_research_cutoff_accepted":
        errors.append("search protocol still reports a superseded workflow state")
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    for name, task_id in (
        ("pa01-s775-s782-citation-pass-2026-09-25.json", "PA-01"),
        ("ns04-perturbation-model-audit.json", "PA-01"),
        ("ecap-trial-registry-audit.json", "PA-06"),
        ("ns15-russian-prior-art-audit.json", "PA-07"),
        ("forbidden-transfer-audit-2026-09-25.json", "EVD-04"),
    ):
        if f"- [x] **{task_id}.**" in todo:
            meta = read_json(name)["meta"]
            if meta.get("status") in {"open", "in_progress", "first_cycle_open"}:
                errors.append(f"{name}: current audit status contradicts closed {task_id}")
            if not meta.get("latest_cutoff") or meta["latest_cutoff"] > cutoff:
                errors.append(f"{name}: current audit cutoff is missing or later than accepted cut")
    return errors


def check_links_and_ids() -> list[str]:
    errors: list[str] = []
    records = json.loads((data_path(DATA, "records.json")).read_text(encoding="utf-8"))
    aliases = json.loads((data_path(DATA, "aliases.json")).read_text(encoding="utf-8"))
    source_ids = {item["id"] for item in records["sources"]} | set(aliases["aliases"])
    clusters = json.loads((data_path(DATA, "clusters.json")).read_text(encoding="utf-8"))
    cluster_ids = {
        item["id"] for group in ("clusters", "retired_clusters") for item in clusters[group]
    }
    for path in [
        ROOT / "TODO.md",
        ROOT / "README.md",
        ROOT / "SKILL.md",
        DATA / "README.md",
        *(ROOT / "docs").rglob("*.md"),
        *(ROOT / "knowledge").rglob("*.md"),
    ]:
        text = path.read_text(encoding="utf-8")
        targets, link_errors = markdown_targets(text)
        errors.extend(f"{path.relative_to(ROOT)}: {error}" for error in link_errors)
        for locator in targets:
            target, _, fragment = locator.partition("#")
            if target.startswith(("http:", "https:", "mailto:", "data:", "/")):
                continue
            destination = path.parent / unquote(target) if target else path
            if not destination.exists():
                errors.append(f"{path.relative_to(ROOT)}: missing link {target}")
            elif fragment and destination.suffix == ".md":
                anchors = markdown_anchors(destination.read_text(encoding="utf-8"))
                if unquote(fragment) not in anchors:
                    errors.append(f"{path.relative_to(ROOT)}: missing anchor {locator}")
        # Historical audit logs explicitly describe orphan IDs; core documents must resolve.
        if "audits" not in path.parts:
            for source_id in set(re.findall(r"\bS\d{3}\b", text)) - source_ids:
                errors.append(f"{path.relative_to(ROOT)}: unknown source {source_id}")
            for cluster_id in set(re.findall(r"\bC\d{2}\b", text)) - cluster_ids:
                errors.append(f"{path.relative_to(ROOT)}: unknown cluster {cluster_id}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="refresh the current manifest")
    args = parser.parse_args()
    files = inventory()
    progress = todo_progress()
    if args.write:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest.update(
            {
                "hash_scope": (
                    "README.md, SKILL.md, TODO.md, registered current data, "
                    "curation bundles/queues, and docs; "
                    "excludes manifest, archive, staging, provenance and frozen batches"
                ),
                "todo_progress": progress,
                "file_count": len(files),
                "files": files,
                "aggregate_sha256": aggregate(files),
            }
        )
        MANIFEST.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors = (
        check_line_endings()
        + check_layout()
        + check_bundles()
        + check_consolidated()
        + check_provenance_references()
        + check_links_and_ids()
        + check_todo_ledger()
        + check_current_state()
        + check_corpus_summaries()
    )
    if manifest["files"] != files or manifest["aggregate_sha256"] != aggregate(files):
        errors.append("release manifest file set or SHA-256 differs from current files")
    if manifest["file_count"] != len(files) or manifest["todo_progress"] != progress:
        errors.append("release manifest counts differ from current files or TODO")
    if manifest["scientific_gate"] != "G0_REVISE":
        errors.append("scientific gate changed from G0_REVISE")
    novelty = json.loads((data_path(DATA, "novelty-landscape.json")).read_text(encoding="utf-8"))
    if novelty["meta"]["operational_disposition"]["saturation"] is not False:
        errors.append("novelty saturation must remain false")
    if errors:
        raise SystemExit("\n".join(errors))
    print(
        f"release OK: {len(files)} files, {len(SCOPES)} bundles, TODO "
        f"{progress['closed']}/{progress['total']}"
    )


if __name__ == "__main__":
    main()
