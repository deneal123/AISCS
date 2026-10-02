"""Knowledge CLI: explicit build/publication, offline inspection and corpus preparation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..core import ResearchRepository
from ..pipeline import atomic_write_json
from .engine import KnowledgeEngine


def parser(subparsers: argparse._SubParsersAction) -> None:
    kb = subparsers.add_parser("knowledge", help="graph/vector corpus and index lifecycle")
    actions = kb.add_subparsers(dest="knowledge_action", required=True)
    actions.add_parser("status")
    prepare = actions.add_parser("prepare")
    prepare.add_argument("--candidates", type=Path)
    prepare.add_argument("--download", action="store_true")
    build = actions.add_parser("build")
    build.add_argument("--offline", action="store_true")
    publish = actions.add_parser("publish")
    publish.add_argument("generation")
    publish.add_argument("--allow-offline", action="store_true")
    actions.add_parser("rollback")
    actions.add_parser("check")
    search = actions.add_parser("search")
    search.add_argument("query")
    search.add_argument("--mode", choices=("hybrid", "lexical", "dense"), default="hybrid")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--include-unreviewed", action="store_true")
    graph = actions.add_parser("graph")
    graph.add_argument("node_id")
    graph.add_argument("--depth", type=int, default=1)
    evaluate = actions.add_parser("evaluate")
    evaluate.add_argument("--mode", choices=("hybrid", "lexical", "dense"), default="hybrid")
    evaluate.add_argument(
        "--suite", type=Path, help="fixed query suite; defaults to regression suite"
    )


def run(args: argparse.Namespace, repository: ResearchRepository) -> dict:
    engine = KnowledgeEngine(repository)
    action = args.knowledge_action
    if action == "check":
        from .verification import verify

        return verify(engine)
    if action == "status":
        return engine.status()
    if action == "prepare":
        from .corpus import portable_manifest, prepare_corpus

        candidates = (
            json.loads(args.candidates.read_text(encoding="utf-8")) if args.candidates else None
        )
        result = prepare_corpus(
            repository, engine.state, candidates=candidates, download=args.download
        )
        atomic_write_json(
            engine.project / "knowledge" / "corpus-manifest.json",
            portable_manifest(result, engine.project),
        )
        return {"counts": result["counts"], "manifest": "knowledge/corpus-manifest.json"}
    if action == "build":
        return engine.build(offline=args.offline)
    if action == "publish":
        return engine.publish(args.generation, allow_offline=args.allow_offline)
    if action == "rollback":
        return engine.rollback()
    if action == "search":
        return engine.search(
            args.query, mode=args.mode, limit=args.limit, include_unreviewed=args.include_unreviewed
        )
    if action == "graph":
        return engine.graph(args.node_id, depth=args.depth)
    from .evaluation import evaluate

    return evaluate(
        engine, args.suite or engine.project / "knowledge" / "evaluation.json", mode=args.mode
    )
