"""Audit coverage and SHA-256 of the registered MaleCNS reconstruction set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_full_morphology import registered_ids, verified_receipt  # noqa: E402


def audit(ids: list[int], directories: list[Path]) -> dict:
    """Check every registered identity; an invalid copy may have a valid fallback."""
    missing = []
    covered = 0
    for body_id in ids:
        if any(verified_receipt(directory, body_id) for directory in directories):
            covered += 1
        else:
            missing.append(body_id)
        if (covered + len(missing)) % 10000 == 0:
            print(
                json.dumps({"checked": covered + len(missing), "missing": len(missing)}), flush=True
            )
    return {
        "registered": len(ids),
        "verified": covered,
        "unavailable_ids": missing,
        "complete": not missing,
        "method": "receipt-identity-and-local-sha256",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--directory", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(registered_ids(args.ids, args.manifest), args.directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temp.replace(args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "unavailable_ids"}))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
