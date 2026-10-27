"""Verify the agents skill contract against workspace-owned profile manifests."""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_ROOT = ROOT / "workspace" / "service" / "domain" / "documents" / "profile_data"
AGENT_CONTRACT = (
    ROOT / "agents/service/domain/documents/skills/profiles.py"
)


def _assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"missing {name}")


def _validate_policy_types(raw: dict[str, object]) -> None:
    for field in ("version", "max_pages"):
        value = raw.get(field)
        if field == "max_pages" and value is None:
            continue
        if type(value) is not int or value <= 0:
            raise ValueError("profile field type invalid")
    for field in ("bibliography_required", "anonymize_supported"):
        if type(raw.get(field, False)) is not bool:
            raise ValueError("profile field type invalid")


def main() -> int:
    try:
        agent_ids = tuple(_assignment(AGENT_CONTRACT, "DOCUMENT_PROFILE_IDS"))
        agent_sections = dict(
            _assignment(AGENT_CONTRACT, "DOCUMENT_PROFILE_REQUIRED_SECTIONS")
        )
        agent_version = str(
            _assignment(AGENT_CONTRACT, "DOCUMENT_PROFILE_CONTRACT_VERSION")
        )
        skill_version = str(
            _assignment(AGENT_CONTRACT, "DOCUMENT_SKILL_CONTRACT_VERSION")
        )
        workspace_ids = []
        workspace_sections = {}
        versions = set()
        for path in sorted(PROFILE_ROOT.glob("*/profile.toml")):
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            _validate_policy_types(raw)
            profile_id = str(raw.get("profile_id") or "")
            if path.parent.name != profile_id:
                raise ValueError("profile directory mismatch")
            workspace_ids.append(profile_id)
            workspace_sections[profile_id] = tuple(raw.get("required_sections") or ())
            versions.add(int(raw.get("version") or 0))
        if tuple(workspace_ids) != agent_ids:
            raise ValueError("agents/workspace profile IDs differ")
        if agent_sections != workspace_sections:
            raise ValueError("agents/workspace required sections differ")
        if agent_version != "s35.v1" or skill_version != agent_version:
            raise ValueError("profile and skill contract versions differ")
        if not versions or min(versions) < 1:
            raise ValueError("profile contract version is invalid")
    except (
        OSError,
        SyntaxError,
        TypeError,
        ValueError,
        tomllib.TOMLDecodeError,
    ) as exc:
        print(f"document profile parity failed: {exc}", file=sys.stderr)
        return 1
    print(f"document profiles aligned: version={agent_version} count={len(agent_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
