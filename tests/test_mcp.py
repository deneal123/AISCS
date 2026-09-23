import asyncio
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from service.core import DataError, load_json, sha256
from service.mcp_server import ResearchMcpService, create_server

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def test_repository_searches_resources_clusters_and_evidence() -> None:
    service = ResearchMcpService(DATA)
    assert service.search_resources(query="FlyGym")["total"] >= 1
    assert service.search_evidence(source_id="S149")["total"] >= 1
    context = service.get_source_context("S063")
    assert context["source"]["id"] == "S031"
    assert context["source"]["alias_resolution"]["requested_id"] == "S063"
    cluster_id = context["clusters"][0]["id"]
    cluster = service.get_cluster(cluster_id, expand_sources=True)
    assert cluster["sources"]


def test_mcp_protocol_initialization_discovery_resource_and_read_tool() -> None:
    async def exercise() -> None:
        async with Client(create_server(DATA)) as client:
            tools = await client.list_tools()
            assert {
                "status",
                "search_sources",
                "get_source_context",
                "search_resources",
                "get_cluster",
                "search_evidence",
                "save_candidate",
                "publish_candidate",
                "review_batch",
                "cluster_manifest",
                "snapshot",
            } == {tool.name for tool in tools.tools}
            resources = await client.list_resources()
            resource_uris = {str(resource.uri) for resource in resources.resources}
            assert "research://guide" in resource_uris
            assert "research://scientific-contract" in resource_uris
            assert "research://human-dataset-matrix" in resource_uris
            templates = await client.list_resource_templates()
            assert {
                "research://source/{source_id}",
                "research://cluster/{cluster_id}",
            } == {template.uri_template for template in templates.resource_templates}
            guide = await client.read_resource("research://guide")
            assert guide.contents
            contract = await client.read_resource("research://scientific-contract")
            assert "STOP-H3-A" in contract.contents[0].text
            result = await client.call_tool("status", {})
            assert result.is_error is not True
            assert result.structured_content["integrity"]["ok"] is True

    asyncio.run(exercise())


def test_mcp_stdio_transport_smoke() -> None:
    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "service.mcp_server"],
            cwd=ROOT,
        )
        async with Client(parameters) as client:
            tools = await client.list_tools()
            assert "status" in {tool.name for tool in tools.tools}
            result = await client.call_tool("search_sources", {"query": "ECAP", "limit": 2})
            assert result.is_error is not True
            assert result.structured_content["limit"] == 2

    asyncio.run(exercise())


def _temporary_data(tmp_path: Path) -> Path:
    destination = tmp_path / "data"
    shutil.copytree(DATA, destination)
    return destination


def _candidate(data: Path, *, source_id: str, url: str) -> dict:
    candidate = deepcopy(load_json(data / "staging" / "source-record.template.json"))
    candidate["id"] = source_id
    candidate["название"] = f"MCP integration fixture {source_id}"
    candidate["identifiers"]["exact_url"] = url
    candidate["provenance"]["import_source"] = "mcp-test"
    return candidate


def test_mcp_write_flow_is_dry_run_then_snapshot_and_atomic_publish(tmp_path: Path) -> None:
    data = _temporary_data(tmp_path)
    service = ResearchMcpService(data)
    candidate = _candidate(data, source_id="S999991", url="https://example.org/mcp-fixture")

    saved = service.save_candidate("fixture", candidate)
    assert saved["saved"] is True
    records_path = data / "records.json"
    before = sha256(records_path)
    archives_before = len(list((data / "archive").glob("*/manifest.json")))

    dry_run = service.publish_candidate("fixture", apply=False)
    assert dry_run["ok"] is True
    assert dry_run["applied"] is False
    assert sha256(records_path) == before
    assert len(list((data / "archive").glob("*/manifest.json"))) == archives_before

    applied = service.publish_candidate("fixture", apply=True)
    assert applied["applied"] is True
    assert applied["integrity"]["ok"] is True
    assert Path(applied["snapshot"]).is_dir()
    assert service.get_source_context("S999991")["source"]["id"] == "S999991"


def test_mcp_blocks_duplicates_traversal_overwrite_and_bad_manifests(tmp_path: Path) -> None:
    data = _temporary_data(tmp_path)
    service = ResearchMcpService(data)
    sources = load_json(data / "records.json")["sources"]
    existing_url = next(item["identifiers"]["exact_url"] for item in sources if item["identifiers"].get("exact_url"))
    existing_doi = next(item["identifiers"]["doi"] for item in sources if item["identifiers"].get("doi"))

    duplicate_url = _candidate(data, source_id="S999992", url=existing_url)
    rejected_url = service.save_candidate("duplicate-url", duplicate_url)
    assert rejected_url["saved"] is False
    assert not (data / "staging" / "inbox" / "duplicate-url.json").exists()

    duplicate_doi = _candidate(
        data, source_id="S999994", url="https://example.org/duplicate-doi"
    )
    duplicate_doi["identifiers"]["doi"] = existing_doi
    rejected_doi = service.save_candidate("duplicate-doi", duplicate_doi)
    assert rejected_doi["saved"] is False
    assert not (data / "staging" / "inbox" / "duplicate-doi.json").exists()

    valid = _candidate(data, source_id="S999993", url="https://example.org/overwrite")
    assert service.save_candidate("overwrite", valid)["saved"] is True
    with pytest.raises(DataError, match="overwrite is not allowed"):
        service.save_candidate("overwrite", valid)
    with pytest.raises(DataError):
        service.save_candidate("../escape", valid)
    with pytest.raises(DataError):
        service.publish_candidate("../escape", apply=True)
    with pytest.raises(DataError):
        service.cluster_manifest("../escape", apply=True)

    broken = data / "curation" / "relevance-5" / "batches" / "broken.json"
    broken.write_text(json.dumps({"source_ids": ["S031"], "decisions": []}), encoding="utf-8")
    result = service.review_batch("broken", apply=False)
    assert result["ok"] is False
    records_before = sha256(data / "records.json")
    apply_result = service.review_batch("broken", apply=True)
    assert apply_result["applied"] is False
    assert sha256(data / "records.json") == records_before
