from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from service.services.simulations import api


@pytest.mark.asyncio
async def test_outgoing_requires_owned_record_and_matching_graph(monkeypatch):
    @asynccontextmanager
    async def session():
        yield object()

    pg = SimpleNamespace(get_session_context=session)
    monkeypatch.setattr(
        api,
        "get_current_container",
        lambda: SimpleNamespace(infra=SimpleNamespace(pg_connector=pg)),
    )
    run = SimpleNamespace(
        state="completed", result={"preview": {"connectome": {"manifest_sha256": "abc"}}}
    )
    owner_check = AsyncMock(return_value=run)
    monkeypatch.setattr(api, "owned", owner_check)
    response = httpx.Response(
        200,
        json={"manifest_sha256": "abc", "items": []},
        request=httpx.Request("GET", "http://test"),
    )
    executor = SimpleNamespace(get=AsyncMock(return_value=response))

    @asynccontextmanager
    async def generator():
        yield executor

    monkeypatch.setattr(api, "generator_client", generator)
    owner, run_id = SimpleNamespace(user_id=uuid4()), uuid4()
    assert (await api.neuron_outgoing(run_id, "123", owner))["items"] == []
    owner_check.assert_awaited_once()
    assert (await api.neuron_incoming(run_id, "123", owner))["items"] == []
    assert executor.get.await_args.args[0].endswith("/123/incoming")
    response = httpx.Response(
        200, json={"manifest_sha256": "different"}, request=httpx.Request("GET", "http://test")
    )
    executor.get.return_value = response
    with pytest.raises(HTTPException) as error:
        await api.neuron_outgoing(run_id, "123", owner)
    assert error.value.status_code == 409
    owner_check.side_effect = HTTPException(404, "not found")
    executor.get.reset_mock()
    with pytest.raises(HTTPException) as error:
        await api.neuron_outgoing(run_id, "123", owner)
    assert error.value.status_code == 404
    executor.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_query_is_rejected_before_access(monkeypatch):
    owner = SimpleNamespace(user_id=uuid4())
    for body_id, offset, limit in [("0", 0, 20), ("1/2", 0, 20), ("1", -1, 20), ("1", 0, 101)]:
        with pytest.raises(HTTPException) as error:
            await api.neuron_outgoing(uuid4(), body_id, owner, offset, limit)
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_morphology_obeys_ownership_and_run_identity(monkeypatch):
    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(api, "get_current_container", lambda: SimpleNamespace(
        infra=SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session))))
    owner_check = AsyncMock(return_value=SimpleNamespace(
        state="completed", result={"preview": {"connectome": {"manifest_sha256": "abc"}}}))
    monkeypatch.setattr(api, "owned", owner_check)
    response = httpx.Response(200, json={"manifest_sha256": "abc", "body_id": "123", "swc": "x"},
                              request=httpx.Request("GET", "http://test"))
    executor = SimpleNamespace(get=AsyncMock(return_value=response))

    @asynccontextmanager
    async def generator():
        yield executor

    monkeypatch.setattr(api, "generator_client", generator)
    owner, run_id = SimpleNamespace(user_id=uuid4()), uuid4()
    assert (await api.neuron_morphology(run_id, "123", owner))["swc"] == "x"
    owner_check.assert_awaited_once()
    executor.get.return_value = httpx.Response(
        200, json={"manifest_sha256": "other", "body_id": "123"},
        request=httpx.Request("GET", "http://test"))
    with pytest.raises(HTTPException) as error:
        await api.neuron_morphology(run_id, "123", owner)
    assert error.value.status_code == 409
    owner_check.side_effect = HTTPException(404, "not found")
    executor.get.reset_mock()
    with pytest.raises(HTTPException) as error:
        await api.neuron_morphology(run_id, "123", owner)
    assert error.value.status_code == 404
    executor.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_synapses_require_owner_and_matching_graph(monkeypatch):
    owner, run_id = SimpleNamespace(user_id=uuid4()), uuid4()
    owner_check = AsyncMock(return_value='abc')
    monkeypatch.setattr(api, 'owned_graph_hash', owner_check)
    data = {'graph_manifest_sha256': 'abc', 'body_id': '123', 'direction': 'incoming',
            'counts_match': True, 'coordinate_frame': 'male-cns-v1.0-native-8nm', 'pairs': []}
    executor = SimpleNamespace(get=AsyncMock(return_value=httpx.Response(
        200, json=data, request=httpx.Request('GET', 'http://test'))))

    @asynccontextmanager
    async def generator():
        yield executor

    monkeypatch.setattr(api, 'generator_client', generator)
    assert (await api.neuron_synapses(run_id, '123', 'incoming', owner))['pairs'] == []
    owner_check.assert_awaited_once_with(run_id, owner)
    executor.get.return_value = httpx.Response(
        200, json={**data, 'graph_manifest_sha256': 'other'}, request=httpx.Request('GET', 'http://test'))
    with pytest.raises(HTTPException) as error:
        await api.neuron_synapses(run_id, '123', 'incoming', owner)
    assert error.value.status_code == 409
    owner_check.side_effect = HTTPException(404, 'not found')
    executor.get.reset_mock()
    with pytest.raises(HTTPException) as error:
        await api.neuron_synapses(run_id, '123', 'incoming', owner)
    assert error.value.status_code == 404
    executor.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_field_checks_owner_and_graph_and_rejects_mismatched_frame(monkeypatch):
    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(api, "get_current_container", lambda: SimpleNamespace(
        infra=SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session))))
    owner_check = AsyncMock(return_value=SimpleNamespace(
        state="completed", result={"preview": {"connectome": {"manifest_sha256": "abc"}}}))
    monkeypatch.setattr(api, "owned", owner_check)
    data = {"manifest_sha256": "abc", "body_id": "123",
            "coordinate_frame": "male-cns-v1.0-native-um",
            "source_sha256": "a" * 64, "medium": "infinite-homogeneous-isotropic",
            "interpretation": "field-only; not excitation or tissue-calibrated",
            "configuration": {"source_um": [0, 10, 0], "return_um": [50, 10, 0],
                              "current_na": 10, "conductivity_s_m": .3, "clearance_um": 1},
            "vertex_ids": [1, 2, 3], "potential_mv": [0, 1, 2],
            "curvature_vertex_ids": [2], "curvature_mv_per_um2": [.1]}
    executor = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(
        200, json=data, request=httpx.Request("POST", "http://test"))))

    @asynccontextmanager
    async def generator():
        yield executor

    monkeypatch.setattr(api, "generator_client", generator)
    owner, run_id = SimpleNamespace(user_id=uuid4()), uuid4()
    request = api.NativeFieldRequest(source_um=(0, 10, 0), return_um=(50, 10, 0),
                                     current_na=10, conductivity_s_m=.3, clearance_um=1)
    assert (await api.neuron_native_field(run_id, "123", request, owner))["body_id"] == "123"
    owner_check.assert_awaited_once()
    executor.post.return_value = httpx.Response(
        200, json={**data, "coordinate_frame": "body-display"},
        request=httpx.Request("POST", "http://test"))
    with pytest.raises(HTTPException) as error:
        await api.neuron_native_field(run_id, "123", request, owner)
    assert error.value.status_code == 409
    for change in ({"configuration": {**data["configuration"], "current_na": 20}},
                   {"potential_mv": [0]}, {"vertex_ids": [1, 1, 3]},
                   {"curvature_vertex_ids": [4]}, {"source_sha256": "bad"}):
        executor.post.return_value = httpx.Response(
            200, json={**data, **change}, request=httpx.Request("POST", "http://test"))
        with pytest.raises(HTTPException) as error:
            await api.neuron_native_field(run_id, "123", request, owner)
        assert error.value.status_code == 409
    executor.post.return_value = httpx.Response(
        200, json=[], request=httpx.Request("POST", "http://test"))
    with pytest.raises(HTTPException) as error:
        await api.neuron_native_field(run_id, "123", request, owner)
    assert error.value.status_code == 409
    owner_check.side_effect = HTTPException(404, "not found")
    executor.post.reset_mock()
    with pytest.raises(HTTPException) as error:
        await api.neuron_native_field(run_id, "123", request, owner)
    assert error.value.status_code == 404
    executor.post.assert_not_awaited()


def test_native_field_contract_does_not_coerce_bool_coordinates():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        api.NativeFieldRequest(source_um=(True, 0, 0), return_um=(50, 10, 0),
                               current_na=10, conductivity_s_m=.3, clearance_um=1)


@pytest.mark.asyncio
async def test_overview_requires_ownership_matching_generation_and_chunk_hash(monkeypatch):
    import hashlib

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(api, "get_current_container", lambda: SimpleNamespace(
        infra=SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session))))
    owner_check = AsyncMock(return_value=SimpleNamespace(
        state="completed", result={"preview": {"connectome": {"manifest_sha256": "abc"}}}))
    monkeypatch.setattr(api, "owned", owner_check)
    raw = b'compressed'
    name = 'overview-000000.bin.gz'
    manifest = {"manifest_sha256": "abc", "chunks": [{"file": name, "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest()}]}
    executor = SimpleNamespace(get=AsyncMock(side_effect=[
        httpx.Response(200, json=manifest, request=httpx.Request("GET", "http://test")),
        httpx.Response(200, content=raw, request=httpx.Request("GET", "http://test")),
    ]))

    @asynccontextmanager
    async def generator():
        yield executor

    monkeypatch.setattr(api, "generator_client", generator)
    owner, run_id = SimpleNamespace(user_id=uuid4()), uuid4()
    assert (await api.cns_overview_chunk(run_id, name, owner)).body == raw
    owner_check.assert_awaited_once()
    executor.get.side_effect = [
        httpx.Response(200, json=manifest, request=httpx.Request("GET", "http://test")),
        httpx.Response(200, content=b'altered!!!', request=httpx.Request("GET", "http://test")),
    ]
    with pytest.raises(HTTPException) as error:
        await api.cns_overview_chunk(run_id, name, owner)
    assert error.value.status_code == 503
    executor.get.side_effect = [httpx.Response(
        200, json={**manifest, "manifest_sha256": "other"},
        request=httpx.Request("GET", "http://test"))]
    with pytest.raises(HTTPException) as error:
        await api.cns_overview(run_id, owner)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        await api.cns_overview_chunk(run_id, '../invalid', owner)
    assert error.value.status_code == 422
    owner_check.side_effect = HTTPException(404, "not found")
    executor.get.reset_mock()
    with pytest.raises(HTTPException) as error:
        await api.cns_overview_chunk(run_id, name, owner)
    assert error.value.status_code == 404
    executor.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_neuropil_requires_ownership_generation_and_intact_mesh(monkeypatch):
    import hashlib

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(api, "get_current_container", lambda: SimpleNamespace(
        infra=SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session))))
    owner_check = AsyncMock(return_value=SimpleNamespace(
        state="completed", result={"preview": {"connectome": {"manifest_sha256": "abc"}}}))
    monkeypatch.setattr(api, "owned", owner_check)
    name, raw = "fullbrain-roi-v4-1.bin.gz", b"compressed"
    manifest = {"manifest_sha256": "abc", "meshes": [{"file": name, "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest()}]}
    executor = SimpleNamespace(get=AsyncMock(side_effect=[
        httpx.Response(200, json=manifest, request=httpx.Request("GET", "http://test")),
        httpx.Response(200, content=raw, request=httpx.Request("GET", "http://test")),
    ]))

    @asynccontextmanager
    async def generator():
        yield executor

    monkeypatch.setattr(api, "generator_client", generator)
    owner, run_id = SimpleNamespace(user_id=uuid4()), uuid4()
    assert (await api.neuropil_part(run_id, name, owner)).body == raw
    executor.get.side_effect = [
        httpx.Response(200, json=manifest, request=httpx.Request("GET", "http://test")),
        httpx.Response(200, content=b"altered!!!", request=httpx.Request("GET", "http://test")),
    ]
    with pytest.raises(HTTPException) as error:
        await api.neuropil_part(run_id, name, owner)
    assert error.value.status_code == 503
    with pytest.raises(HTTPException) as error:
        await api.neuropil_part(run_id, "../invalid", owner)
    assert error.value.status_code == 422
    owner_check.side_effect = HTTPException(404, "not found")
    executor.get.reset_mock()
    with pytest.raises(HTTPException) as error:
        await api.neuropil_part(run_id, name, owner)
    assert error.value.status_code == 404
    executor.get.assert_not_awaited()
