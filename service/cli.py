"""Command-line interface for validation, curation, and export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .core import DataError, ResearchRepository, default_data_dir
from .curation import build_queue, cluster_apply, cluster_check, review_apply, review_check
from .integrity import validate_repository
from .novelty import novelty_summary, search_novelty
from .pipeline import (
    atomic_write_json,
    new_candidate,
    publish_candidates,
    review_candidates,
    snapshot_repository,
)
from .st_curation import build_st_queue, st_review_apply, st_review_check


def emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def configure_console() -> None:
    """Keep Russian metadata readable when PowerShell uses a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="researchctl", description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir(),
        help="directory with canonical JSON files",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="run all repository integrity gates")
    subparsers.add_parser("stats", help="show corpus and evidence counters")
    subparsers.add_parser("completeness", help="show schema-2 terminal-resolution report")
    subparsers.add_parser("novelty-check", help="validate and summarize the novelty catalogue")
    migrate_v2 = subparsers.add_parser(
        "migrate-v2", help="preview or apply the one-time schema-2 migration"
    )
    migrate_v2.add_argument("--apply", action="store_true")
    novelty_queue = subparsers.add_parser(
        "novelty-queue", help="show open prior-art search streams"
    )
    novelty_queue.add_argument("--status", default="open")
    novelty_search = subparsers.add_parser(
        "novelty-search", help="search the unranked novelty catalogue"
    )
    novelty_search.add_argument("query", nargs="?", default=None)
    novelty_search.add_argument("--prior-art-outcome")
    novelty_search.add_argument("--limit", type=int, default=50)
    novelty_search.add_argument("--offset", type=int, default=0)

    new = subparsers.add_parser("new", help="generate the next canonical-id candidate")
    new.add_argument("title")
    new.add_argument("--output", type=Path, help="optional staging JSON path")

    search = subparsers.add_parser("search", help="lexical search over canonical sources")
    search.add_argument("query", nargs="?", default=None)
    search.add_argument("--validation-status")
    search.add_argument("--screening-status")
    search.add_argument("--evidence-role")
    search.add_argument("--target-construct")
    search.add_argument("--risk-flag")
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--offset", type=int, default=0)

    get = subparsers.add_parser("get", help="get one source and resolve legacy aliases")
    get.add_argument("source_id")

    export = subparsers.add_parser("export", help="export canonical sources as JSONL")
    export.add_argument("output", type=Path)

    snapshot = subparsers.add_parser("snapshot", help="create a hashed immutable snapshot")
    snapshot.add_argument("--label")

    stage = subparsers.add_parser("stage", help="validate a candidate source batch without writing")
    stage.add_argument("input", type=Path)

    publish = subparsers.add_parser(
        "publish", help="review or atomically publish candidate sources"
    )
    publish.add_argument("input", type=Path)
    publish.add_argument(
        "--apply",
        action="store_true",
        help="write after validation; without this flag the command is a dry-run",
    )

    queue = subparsers.add_parser("queue", help="build deterministic curation batches")
    queue.add_argument("--relevance", type=int, default=5)
    queue.add_argument("--status", default="unverified")
    queue.add_argument("--batch-size", type=int, default=20)

    review_check_parser = subparsers.add_parser(
        "review-check", help="validate a completed curation batch"
    )
    review_check_parser.add_argument("batch")

    review_apply_parser = subparsers.add_parser(
        "review-apply", help="validate and atomically apply a curation batch"
    )
    review_apply_parser.add_argument("batch")
    review_apply_parser.add_argument("--apply", action="store_true")

    cluster_check_parser = subparsers.add_parser(
        "cluster-check", help="validate a reviewed cluster-assignment manifest"
    )
    cluster_check_parser.add_argument("manifest", type=Path)

    cluster_apply_parser = subparsers.add_parser(
        "cluster-apply", help="atomically apply a reviewed cluster-assignment manifest"
    )
    cluster_apply_parser.add_argument("manifest", type=Path)
    cluster_apply_parser.add_argument("--apply", action="store_true")

    st_queue = subparsers.add_parser("st-queue", help="build ST resource review batches")
    st_queue.add_argument("--batch-size", type=int, default=15)

    st_check = subparsers.add_parser("st-review-check", help="validate an ST review batch")
    st_check.add_argument("batch")

    st_apply = subparsers.add_parser("st-review-apply", help="apply an ST review batch")
    st_apply.add_argument("batch")
    st_apply.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console()
    args = build_parser().parse_args(argv)
    root = args.data_dir.resolve()
    try:
        if args.command == "validate":
            report = validate_repository(root)
            emit(report)
            return 0 if report["ok"] else 1
        repository = ResearchRepository(root)
        if args.command == "stats":
            emit({"meta": repository.metadata(), "evidence": repository.evidence_summary()})
        elif args.command == "completeness":
            emit(repository.completeness_report())
        elif args.command == "novelty-check":
            report = validate_repository(root)
            emit({"ok": report["ok"], "errors": report["errors"], **novelty_summary(root)})
            return 0 if report["ok"] else 1
        elif args.command == "migrate-v2":
            records = json.loads((root / "records.json").read_text(encoding="utf-8"))
            current = records.get("meta", {}).get("schema_version")
            if current == "2.0.0":
                emit({"ok": True, "applied": False, "status": "already_schema_2"})
            else:
                if root != default_data_dir().resolve():
                    raise DataError(
                        "schema-2 migration currently supports only the canonical data dir"
                    )
                from migrations.upgrade_schema_2_0 import migrate

                outputs = migrate()
                if args.apply:
                    for name, payload in outputs.items():
                        atomic_write_json(root / name, payload)
                emit(
                    {
                        "ok": True,
                        "applied": args.apply,
                        "files": sorted(outputs),
                        "records": len(outputs["records.json"]["sources"]),
                    }
                )
        elif args.command == "novelty-queue":
            protocol = json.loads((root / "search-protocol.json").read_text(encoding="utf-8"))
            items = [
                item
                for item in protocol.get("search_streams", [])
                if args.status == "all" or item.get("status") == args.status
            ]
            emit({"items": items, "total": len(items), "status": args.status})
        elif args.command == "novelty-search":
            if args.limit < 1 or args.limit > 500 or args.offset < 0:
                raise DataError("limit must be 1..500 and offset must be non-negative")
            emit(
                search_novelty(
                    root,
                    query=args.query,
                    prior_art_outcome=args.prior_art_outcome,
                    limit=args.limit,
                    offset=args.offset,
                )
            )
        elif args.command == "new":
            candidate = new_candidate(root, args.title)
            if args.output:
                output = args.output.resolve()
                if output.exists():
                    raise DataError(f"refusing to overwrite existing candidate: {output}")
                candidate["provenance"]["import_source"] = str(args.output)
                atomic_write_json(output, candidate)
                emit({"ok": True, "id": candidate["id"], "output": str(output)})
            else:
                emit(candidate)
        elif args.command == "search":
            if args.limit < 1 or args.limit > 500 or args.offset < 0:
                raise DataError("limit must be 1..500 and offset must be non-negative")
            emit(
                repository.list_sources(
                    query=args.query,
                    validation_status=args.validation_status,
                    screening_status=args.screening_status,
                    evidence_role=args.evidence_role,
                    target_construct=args.target_construct,
                    risk_flag=args.risk_flag,
                    limit=args.limit,
                    offset=args.offset,
                )
            )
        elif args.command == "get":
            source = repository.get_source(args.source_id)
            if source is None:
                raise DataError(f"source not found: {args.source_id}")
            emit(source)
        elif args.command == "export":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(repository.export_jsonl(), encoding="utf-8", newline="\n")
            emit(
                {
                    "ok": True,
                    "output": str(args.output),
                    "sources": repository.evidence_summary()["total"],
                }
            )
        elif args.command == "snapshot":
            destination = snapshot_repository(root, args.label)
            emit({"ok": True, "snapshot": str(destination)})
        elif args.command == "stage":
            review = review_candidates(root, args.input)
            emit({key: value for key, value in review.items() if key != "candidates"})
            return 0 if review["ok"] else 1
        elif args.command == "publish":
            result = publish_candidates(root, args.input, apply=args.apply)
            emit(result)
            return 0 if result["ok"] else 1
        elif args.command == "queue":
            emit(
                build_queue(
                    root,
                    relevance=args.relevance,
                    status=args.status,
                    batch_size=args.batch_size,
                )
            )
        elif args.command == "review-check":
            result = review_check(root, args.batch)
            emit(result)
            return 0 if result["ok"] else 1
        elif args.command == "review-apply":
            result = review_apply(root, args.batch, apply=args.apply)
            emit(result)
            return 0 if result["ok"] else 1
        elif args.command == "cluster-check":
            result = cluster_check(root, args.manifest)
            emit(result)
            return 0 if result["ok"] else 1
        elif args.command == "cluster-apply":
            result = cluster_apply(root, args.manifest, apply=args.apply)
            emit(result)
            return 0 if result["ok"] else 1
        elif args.command == "st-queue":
            emit(build_st_queue(root, batch_size=args.batch_size))
        elif args.command == "st-review-check":
            result = st_review_check(root, args.batch)
            emit(result)
            return 0 if result["ok"] else 1
        elif args.command == "st-review-apply":
            result = st_review_apply(root, args.batch, apply=args.apply)
            emit(result)
            return 0 if result["ok"] else 1
        return 0
    except DataError as exc:
        emit({"ok": False, "error": "data_invalid", "detail": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
