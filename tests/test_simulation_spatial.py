from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from service.services.simulations import api
from service.services.simulations.api import SpatialCandidatesRequest, valid_spatial_candidates


def test_candidate_contract_rejects_mismatch_duplicates_and_impossible_distances():
    request = SpatialCandidatesRequest(source_um=(0, 0, 0), return_um=(10, 0, 0), radius_um=3)
    row = {"body_id": 1, "source_sha256": "a" * 64, "distance_um": 2, "child_node_id": 7,
           "contact": 0, "edge_fraction": .5, "isolated_root": False,
           "conservative_clearance_um": [1.9, 3.2],
           "geometry": {"components": 1, "isolated_roots": 0, "zero_length_edges": 0,
                        "nonpositive_radius_edges": 0}}
    result = {"configuration": request.model_dump(mode="json"), "manifest_sha256": "graph",
              "coordinate_frame": "male-cns-v1.0-native-um", "indexed": 3,
              "bounding_box_matches": 1, "candidates": [row],
              "interpretation": "centerline proximity in indexed snapshot; not excitation"}
    assert valid_spatial_candidates(result, request, "graph", 3)
    assert not valid_spatial_candidates(result, request, "graph", 4)
    assert not valid_spatial_candidates(result, request, "different", 3)
    assert not valid_spatial_candidates({**result, "candidates": [row, row]}, request, "graph", 3)
    assert not valid_spatial_candidates({**result, "candidates": [{**row, "distance_um": 4}]},
                                        request, "graph", 3)
    assert not valid_spatial_candidates({**result, "candidates": [{**row, "body_id": True}]},
                                        request, "graph", 3)


def test_recording_contacts_require_verified_clearance_for_every_candidate():
    request = SpatialCandidatesRequest(source_um=(0, 0, 0), return_um=(10, 0, 0), radius_um=3,
                                       electrode_um=(0, 3, 0), reference_um=(10, 3, 0))
    row = {"body_id": 1, "source_sha256": "a" * 64, "distance_um": 2, "child_node_id": 7,
           "contact": 0, "edge_fraction": .5, "isolated_root": False,
           "conservative_clearance_um": [1.9, 3.2], "recording_clearance_um": [2.5, 2.6],
           "geometry": {"components": 1, "isolated_roots": 0, "zero_length_edges": 0,
                        "nonpositive_radius_edges": 0}}
    result = {"configuration": request.model_dump(mode="json"), "manifest_sha256": "graph",
              "coordinate_frame": "male-cns-v1.0-native-um", "indexed": 3,
              "bounding_box_matches": 1, "candidates": [row],
              "interpretation": "centerline proximity in indexed snapshot; not excitation"}
    assert valid_spatial_candidates(result, request, "graph", 3)
    assert not valid_spatial_candidates({**result, "candidates": [{**row,
        "recording_clearance_um": None}]}, request, "graph", 3)


@pytest.mark.asyncio
async def test_spatial_route_checks_owner_before_executor(monkeypatch):
    owner_check = AsyncMock(return_value=("graph", 3))
    monkeypatch.setattr(api, "owned_spatial_graph", owner_check)
    request = SpatialCandidatesRequest(source_um=(0, 0, 0), return_um=(10, 0, 0), radius_um=3)
    data = {"configuration": request.model_dump(mode="json"), "manifest_sha256": "graph",
            "coordinate_frame": "male-cns-v1.0-native-um", "indexed": 3,
            "bounding_box_matches": 0, "candidates": [],
            "interpretation": "centerline proximity in indexed snapshot; not excitation"}
    client = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(
        200, json=data, request=httpx.Request("POST", "http://test"))))

    @asynccontextmanager
    async def generator():
        yield client

    monkeypatch.setattr(api, "generator_client", generator)
    owner, run_id = SimpleNamespace(user_id=uuid4()), uuid4()
    assert (await api.find_spatial_candidates(run_id, request, owner))["candidates"] == []
    client.post.return_value = httpx.Response(429, request=httpx.Request("POST", "http://test"))
    with pytest.raises(HTTPException) as busy:
        await api.find_spatial_candidates(run_id, request, owner)
    assert busy.value.status_code == 429
    owner_check.side_effect = HTTPException(404, "not found")
    client.post.reset_mock()
    with pytest.raises(HTTPException) as error:
        await api.find_spatial_candidates(run_id, request, owner)
    assert error.value.status_code == 404
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_graph_requires_recorded_positive_neuron_count(monkeypatch):
    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(api, "get_current_container", lambda: SimpleNamespace(
        infra=SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session))))
    run = SimpleNamespace(state="completed", result={"preview": {"connectome": {
        "manifest_sha256": "graph", "neurons": 3}}})
    owned = AsyncMock(return_value=run)
    monkeypatch.setattr(api, "owned", owned)
    owner, run_id = SimpleNamespace(user_id=uuid4()), uuid4()
    assert await api.owned_spatial_graph(run_id, owner) == ("graph", 3)
    run.result["preview"]["connectome"]["neurons"] = True
    with pytest.raises(HTTPException) as error:
        await api.owned_spatial_graph(run_id, owner)
    assert error.value.status_code == 409
