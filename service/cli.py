"""Command-line interface for a document sidecar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .core import DocumentSidecar, SidecarError


def emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    validate = sub.add_parser("validate")
    validate.add_argument("--profile", choices=("draft", "release"), default="draft")
    sub.add_parser("list")
    get = sub.add_parser("get")
    get.add_argument("document_id")
    build = sub.add_parser("build")
    build.add_argument("document_id")
    build.add_argument("--profile", choices=("draft", "release"), default="draft")
    build.add_argument("--check", action="store_true")
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--label", required=True)
    imported = sub.add_parser("import-research")
    imported.add_argument("research_dir", type=Path)
    imported.add_argument("refs", nargs="+")
    imported.add_argument("--apply", action="store_true")
    release = sub.add_parser("release")
    release.add_argument("document_id")
    release.add_argument("version")
    release.add_argument("--apply", action="store_true")
    package = sub.add_parser("package")
    package.add_argument("document_id")
    package.add_argument("--apply", action="store_true")
    return result


def main() -> None:
    args = parser().parse_args()
    sidecar = DocumentSidecar()
    try:
        if args.command == "status":
            payload = sidecar.status()
        elif args.command == "validate":
            payload = sidecar.validate(profile=args.profile)
        elif args.command == "list":
            payload = sidecar.list_documents()
        elif args.command == "get":
            payload = sidecar.get_document(args.document_id)
            if payload is None:
                raise SidecarError("document not found")
        elif args.command == "build":
            payload = sidecar.build(args.document_id, args.profile, apply=not args.check)
        elif args.command == "snapshot":
            payload = sidecar.snapshot(args.label)
        elif args.command == "import-research":
            payload = sidecar.import_research(args.research_dir, args.refs, apply=args.apply)
        elif args.command == "release":
            payload = sidecar.release(args.document_id, args.version, apply=args.apply)
        elif args.command == "package":
            payload = sidecar.package(args.document_id, apply=args.apply)
        else:
            raise SidecarError("unsupported command")
    except SidecarError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(2) from exc
    emit(payload)
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
