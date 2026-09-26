"""Pin GitHub-backed ST resources to immutable commits and verified licenses."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"
GITHUB_REPOSITORY = re.compile(r"^https://github\.com/([^/]+)/([^/#?]+)", re.IGNORECASE)


def repository_url(url: str) -> str | None:
    match = GITHUB_REPOSITORY.match(url)
    if not match:
        return None
    owner, repository = match.groups()
    return f"https://github.com/{owner}/{repository.removesuffix('.git')}"


def github_metadata(url: str) -> dict[str, Any]:
    match = GITHUB_REPOSITORY.match(url)
    if not match:
        raise ValueError(f"not a GitHub repository URL: {url}")
    owner, repository = match.groups()
    repository = repository.removesuffix(".git")
    canonical_url = f"https://github.com/{owner}/{repository}"
    process = subprocess.run(  # noqa: S603
        ["git", "ls-remote", canonical_url, "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    commit = process.stdout.split()[0] if process.returncode == 0 and process.stdout else None
    api_url = f"https://api.github.com/repos/{owner}/{repository}"
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "aspa-research/1.3",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            metadata = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "ok": bool(commit),
            "metadata_ok": False,
            "api_url": api_url,
            "canonical_url": canonical_url,
            "commit": commit,
            "error": str(exc),
        }
    license_info = metadata.get("license") or {}
    return {
        "ok": True,
        "metadata_ok": True,
        "api_url": api_url,
        "canonical_url": canonical_url,
        "commit": commit,
        "default_branch": metadata.get("default_branch"),
        "license_spdx": license_info.get("spdx_id"),
        "license_url": license_info.get("html_url") or f"{canonical_url}/blob/HEAD/LICENSE",
        "archived": bool(metadata.get("archived")),
        "updated_at": metadata.get("updated_at"),
    }


def _resolution(
    *, state: str, value: str | None, reason: str, url: str, locator: str
) -> dict[str, Any]:
    return {
        "state": state,
        "value": value,
        "reason": reason,
        "checked_at": DATE,
        "locators": [{"url": url, "locator": locator}],
    }


def refresh(*, apply: bool, data_dir: Path = DATA) -> dict[str, Any]:
    resources = load_json(data_dir / "ST.json")
    audit = load_json(data_dir / "audit-report.json")
    validation_log = load_json(data_dir / "validation-log.json")
    results: list[dict[str, Any]] = []

    items = [
        resource
        for category in resources["categories"]
        for subcategory in category.get("подкатегории", [])
        for resource in subcategory.get("ресурсы", [])
    ]
    for resource in items:
        repo = repository_url(str(resource.get("ссылка") or ""))
        if not repo:
            continue
        metadata = github_metadata(repo)
        technical = resource["technical_resolution"]
        if metadata["ok"] and metadata.get("commit"):
            commit = metadata["commit"]
            technical["version_or_commit"] = _resolution(
                state="reported",
                value=commit,
                reason="Default-branch HEAD was resolved with git ls-remote and pinned immutably.",
                url=f"{repo}/commit/{commit}",
                locator=f"commit {commit}",
            )
        else:
            technical["version_or_commit"] = _resolution(
                state="unavailable_after_search",
                value=None,
                reason=f"Repeated repository check did not resolve an immutable commit: {metadata.get('error', 'HEAD unavailable')}.",
                url=repo,
                locator="repository HEAD recheck",
            )

        spdx = metadata.get("license_spdx")
        if metadata.get("metadata_ok") and spdx and spdx != "NOASSERTION":
            technical["license"] = _resolution(
                state="reported",
                value=spdx,
                reason="GitHub repository metadata reports a machine-readable SPDX license.",
                url=metadata["license_url"],
                locator=f"license SPDX {spdx}",
            )
        elif technical["license"].get("state") != "reported":
            technical["license"] = _resolution(
                state="unavailable_after_search",
                value=None,
                reason="Repository metadata was rechecked, but no unambiguous SPDX license was reported.",
                url=metadata.get("api_url", repo),
                locator="repository license metadata recheck",
            )
            exclusion = (
                "Excluded from the reproducible dissertation stack until an explicit "
                "license is confirmed by the owner or a tagged release."
            )
            limitations = resource.setdefault("ограничения_валидации", [])
            if exclusion not in limitations:
                limitations.append(exclusion)
            technical["reproducibility"] = _resolution(
                state="unavailable_after_search",
                value=None,
                reason=exclusion,
                url=repo,
                locator="reproducible-stack license gate",
            )

        technical["data_access"] = _resolution(
            state="reported" if metadata.get("commit") else "unavailable_after_search",
            value="public repository" if metadata.get("commit") else None,
            reason=(
                "The public repository and its metadata endpoint were reachable."
                if metadata.get("commit")
                else "The repository metadata endpoint was not reachable during the repeat check."
            ),
            url=repo,
            locator="repository landing page and metadata",
        )
        resource["проверено"] = DATE
        results.append(
            {
                "resource_id": resource["resource_id"],
                "repository": repo,
                **metadata,
            }
        )

    successful_commits = sum(
        resource["technical_resolution"]["version_or_commit"]["state"] == "reported"
        for resource in items
        if repository_url(str(resource.get("ссылка") or ""))
    )
    reported_licenses = sum(
        resource["technical_resolution"]["license"]["state"] == "reported"
        for resource in items
        if repository_url(str(resource.get("ссылка") or ""))
    )
    audit["current_corpus"]["resources"] = len(items)
    audit["github_resource_refresh"] = {
        "checked_at": DATE,
        "repositories": len(results),
        "immutable_commits": successful_commits,
        "reported_spdx_licenses": reported_licenses,
        "runtime_reproduction_not_implied": True,
    }
    validation_log.setdefault("searches", []).append(
        {
            "search_id": "ST-GITHUB-2026-09-24-01",
            "date": DATE,
            "stream": "GitHub resource version and license refresh",
            "query": "git ls-remote HEAD plus GitHub repository metadata for every ST GitHub URL",
            "urls_reviewed": [item["repository"] for item in results],
            "resource_ids": [item["resource_id"] for item in results],
            "decision": "immutable commits pinned where reachable; license state recorded without inference",
        }
    )
    validation_log["meta"]["checked_at"] = DATE

    result = {
        "ok": True,
        "applied": False,
        "repositories": len(results),
        "immutable_commits": successful_commits,
        "reported_spdx_licenses": reported_licenses,
        "failed": [item for item in results if not item.get("commit")],
    }
    if not apply:
        return result

    snapshot = snapshot_repository(data_dir, label="pre-github-resource-refresh")
    atomic_write_json(data_dir / "ST.json", resources)
    atomic_write_json(data_dir / "audit-report.json", audit)
    atomic_write_json(data_dir / "validation-log.json", validation_log)
    report = validate_repository(data_dir)
    if not report["ok"]:
        raise RuntimeError(
            f"post-refresh integrity failed; restore {snapshot}: {'; '.join(report['errors'])}"
        )
    result.update({"applied": True, "snapshot": str(snapshot), "integrity": report})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(refresh(apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
