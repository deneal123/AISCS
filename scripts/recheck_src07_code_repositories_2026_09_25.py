"""Check current GitHub HEADs for seven 2026 code-only cards."""

# ruff: noqa: E501 -- keep API field locators and scientific boundaries explicit.

import argparse
import json
import subprocess
import time
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "src07-code-repository-recheck-2026-09-25.json"
SOURCE_IDS = ("S200", "S201", "S224", "S292", "S732", "S733", "S737")


def resources(node: object):
    if isinstance(node, dict):
        if "resource_id" in node and "ссылка" in node:
            yield node
        for child in node.values():
            yield from resources(child)
    elif isinstance(node, list):
        for child in node:
            yield from resources(child)


def github_json(url: str) -> dict:
    result = subprocess.run(
        ["curl.exe", "-L", "-sS", "--max-time", "20", "-A", "AspaResearch/1.0 (source version review)", "-H", "Accept: application/vnd.github+json", "-w", "\n%{http_code}", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    body, _, code = result.stdout.rpartition("\n")
    if result.returncode or code != "200":
        raise ValueError(f"GitHub API failed: {url}, curl={result.returncode}, http={code}")
    return json.loads(body)


def updated() -> dict:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    st = json.loads((DATA / "ST.json").read_text(encoding="utf-8"))
    by_id = {source["id"]: source for source in records["sources"]}
    by_url = {
        item["ссылка"].rstrip("/").lower(): item
        for item in resources(st)
        if isinstance(item.get("ссылка"), str)
    }
    rows = []
    for index, sid in enumerate(SOURCE_IDS):
        if index:
            time.sleep(0.5)
        source = by_id[sid]
        url = source["identifiers"]["exact_url"].rstrip("/")
        if not url.startswith("https://github.com/"):
            raise ValueError(f"Not a GitHub source: {sid}")
        slug = url.removeprefix("https://github.com/")
        repo_api = f"https://api.github.com/repos/{slug}"
        repo = github_json(repo_api)
        commit_api = f"{repo_api}/commits/{repo['default_branch']}"
        head = github_json(commit_api)
        resource = by_url.get(url.lower())
        pin = resource["technical_resolution"]["version_or_commit"].get("value") if resource else None
        rows.append({
            "source_id": sid, "repo": slug, "source_url": url,
            "resource_id": resource["resource_id"] if resource else None,
            "pinned_commit": pin,
            "head_commit": head["sha"],
            "head_date": head["commit"]["committer"]["date"],
            "head_message_first_line": head["commit"]["message"].splitlines()[0],
            "default_branch": repo["default_branch"],
            "archived": repo["archived"], "disabled": repo["disabled"],
            "pin_relation": "no_active_ST_resource" if resource is None else ("matches_current_head" if pin == head["sha"] else "historical_immutable_pin"),
            "locators": [
                {"url": repo_api, "locator": "default_branch, archived, disabled"},
                {"url": commit_api, "locator": "sha, commit.committer.date, commit.message"},
            ],
        })
    return {
        "meta": {
            "schema_version": "1.0.0", "checked_at": "2026-09-25",
            "scope": "Current repository HEADs for seven 2026 code-only cards",
            "status": "code_head_rechecked",
            "boundary": "A current default-branch HEAD is not the commit used in a manuscript, runtime study or published simulation. Historical ST pins stay immutable.",
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and OUTPUT.exists():
        raise ValueError(f"Dated audit already exists: {OUTPUT}")
    if not args.apply:
        print(f"Dry run: {len(SOURCE_IDS)} GitHub source cards")
        return
    audit = updated()
    snapshot = snapshot_repository(DATA, label="pre-src07-code-head-recheck")
    atomic_write_json(OUTPUT, audit)
    print(f"Checked {len(audit['rows'])} repositories; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
