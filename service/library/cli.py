"""Library CLI: explicit preparation, build and publication of the separate book index."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..core import ResearchRepository
from .engine import LibraryEngine


def parser(subparsers: argparse._SubParsersAction) -> None:
    library = subparsers.add_parser("library", help="separate methodology-book index")
    actions = library.add_subparsers(dest="library_action", required=True)
    actions.add_parser("status")
    actions.add_parser("books")
    prepare = actions.add_parser("prepare")
    prepare.add_argument("--download", action="store_true", help="fetch catalog URL originals")
    prepare.add_argument("--source-dir", type=Path, help="override catalog source_dir")
    build = actions.add_parser("build")
    build.add_argument("--offline", action="store_true")
    publish = actions.add_parser("publish")
    publish.add_argument("generation")
    publish.add_argument("--allow-offline", action="store_true")
    actions.add_parser("rollback")
    actions.add_parser("check")
    export = actions.add_parser("export", help="portable snapshot for another server")
    export.add_argument("--output", type=Path, help="default: .knowledge/snapshots/")
    restore = actions.add_parser("restore", help="place a verified snapshot, then build")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--force", action="store_true", help="overwrite existing files")
    search = actions.add_parser("search")
    search.add_argument("query")
    search.add_argument("--book", action="append", dest="books", help="restrict to a book ID")
    search.add_argument("--mode", choices=("hybrid", "lexical", "dense"), default="hybrid")
    search.add_argument("--limit", type=int, default=8)
    passage = actions.add_parser("passage")
    passage.add_argument("chunk_id")
    passage.add_argument("--context", type=int, default=1)
    evaluate = actions.add_parser("evaluate")
    evaluate.add_argument("--mode", choices=("hybrid", "lexical", "dense"), default="hybrid")
    evaluate.add_argument("--suite", type=Path, help="default: knowledge/library/evaluation.json")


def run(args: argparse.Namespace, repository: ResearchRepository) -> dict:
    engine = LibraryEngine(repository.data_dir.parent)
    action = args.library_action
    if action == "status":
        return engine.status()
    if action == "books":
        return engine.books()
    if action == "prepare":
        return engine.prepare(download=args.download, source_dir=args.source_dir)
    if action == "build":
        return engine.build(offline=args.offline)
    if action == "publish":
        return engine.publish(args.generation, allow_offline=args.allow_offline)
    if action == "rollback":
        return engine.rollback()
    if action == "check":
        return engine.check()
    if action == "export":
        return engine.export(args.output)
    if action == "restore":
        return engine.restore(args.archive, force=args.force)
    if action == "search":
        return engine.search(args.query, book_ids=args.books, mode=args.mode, limit=args.limit)
    if action == "passage":
        return engine.passage(args.chunk_id, context=args.context)
    suite = args.suite or engine.project / "knowledge" / "library" / "evaluation.json"
    return engine.evaluate(suite, mode=args.mode)
