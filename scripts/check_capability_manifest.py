#!/usr/bin/env python3
"""Validate the S29 safe capability manifest and billing parity offline."""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents"
EXPECTED_KEYS = {"version", "digest", "counts", "route_names", "billing_names"}
COUNT_KEYS = {"agents", "workflows", "native_tools"}
FORBIDDEN_KEYS = {"prompt", "schema", "module", "callable", "path", "description"}


def _fail(message: str) -> None:
    print(f"capability manifest mismatch: {message}", file=sys.stderr)
    raise SystemExit(1)


def _literal_string_set(tree: ast.Module, name: str) -> set[str]:
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            continue
        value = node.value
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "frozenset"
            and len(value.args) == 1
        ):
            _fail(f"{name} is not a literal frozenset")
        literal = ast.literal_eval(value.args[0])
        if not isinstance(literal, set) or not all(
            isinstance(item, str) for item in literal
        ):
            _fail(f"{name} contains a non-string value")
        return literal
    _fail(f"{name} was not found")
    return set()


def _active_billable_contract() -> set[str]:
    path = AGENTS / "service" / "contracts.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    billable = _literal_string_set(tree, "BILLABLE_TOOLS")
    legacy = _literal_string_set(tree, "LEGACY_BILLING_NAMES")
    if not legacy.issubset(billable):
        _fail("legacy billing names are not part of the wire contract")
    return billable - legacy


def _runtime_manifest() -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "service.presentation.cli.capability_manifest"],
        cwd=AGENTS,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        _fail("compiler preflight failed")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        _fail("CLI must emit exactly one JSON line")
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError:
        _fail("CLI output is not JSON")
    if not isinstance(payload, dict):
        _fail("manifest root is not an object")
    return payload


def main() -> int:
    manifest = _runtime_manifest()
    if set(manifest) != EXPECTED_KEYS:
        _fail("unsafe or missing top-level fields")
    if set(manifest.get("counts", {})) != COUNT_KEYS:
        _fail("count fields differ")
    if not all(
        isinstance(value, int) and value > 0 for value in manifest["counts"].values()
    ):
        _fail("counts must be positive integers")

    digest = manifest.get("digest")
    if not isinstance(digest, str) or len(digest) != hashlib.sha256().digest_size * 2:
        _fail("digest is not a SHA-256 hex value")
    try:
        bytes.fromhex(digest)
    except ValueError:
        _fail("digest is not hexadecimal")

    for field in ("route_names", "billing_names"):
        values = manifest.get(field)
        if not isinstance(values, list) or values != sorted(set(values)):
            _fail(f"{field} must be a sorted unique list")
        if not all(isinstance(value, str) and value for value in values):
            _fail(f"{field} contains an invalid name")
    if set(manifest["billing_names"]) != _active_billable_contract():
        _fail("compiled billing names differ from active BILLABLE_TOOLS")

    serialized = json.dumps(manifest, sort_keys=True).lower()
    if any(f'"{key}"' in serialized for key in FORBIDDEN_KEYS):
        _fail("manifest exposes a forbidden structural field")

    print(
        "capability manifest: "
        f"{manifest['version']} {manifest['digest'][:12]} "
        f"agents={manifest['counts']['agents']} "
        f"workflows={manifest['counts']['workflows']} "
        f"native_tools={manifest['counts']['native_tools']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
