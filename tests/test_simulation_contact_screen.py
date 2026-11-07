from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from service.services.simulations import api


def example():
    request = api.ContactScreenRequest(source_um=(0, 0, 0), return_um=(10, 0, 0),
                                       electrode_um=(0, 5, 0), reference_um=(10, 5, 0),
                                       clearance_um=1)
    row = {'body_id': 1, 'source_sha256': 'a' * 64, 'contact_indices': [0, 2],
           'conservative_clearance_um': [.5, 9., -1., 8.]}
    result = {'configuration': request.model_dump(mode='json'), 'manifest_sha256': 'graph',
              'coordinate_frame': 'male-cns-v1.0-native-um', 'indexed': 3, 'examined': 2,
              'potential_intersections': [row],
              'interpretation': 'conservative SWC snapshot screening; '
                                'not tissue anatomy or activation'}
    return request, row, result


def test_contact_result_rejects_mismatch_duplicates_and_wrong_flags():
    request, row, result = example()
    assert api.valid_contact_screen(result, request, 'graph', 3)
    assert not api.valid_contact_screen(result, request, 'other', 3)
    assert not api.valid_contact_screen({**result, 'potential_intersections': [row, row]},
                                        request, 'graph', 3)
    assert not api.valid_contact_screen({**result, 'potential_intersections': [
        {**row, 'contact_indices': [0]}]}, request, 'graph', 3)
    assert not api.valid_contact_screen({**result, 'potential_intersections': [
        {**row, 'conservative_clearance_um': [float('nan'), 9., -1., 8.]}]}, request, 'graph', 3)


@pytest.mark.asyncio
async def test_contact_route_checks_ownership_before_executor(monkeypatch):
    owner_check = AsyncMock(return_value=('graph', 3))
    monkeypatch.setattr(api, 'owned_spatial_graph', owner_check)
    request, _, data = example()
    client = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(
        200, json=data, request=httpx.Request('POST', 'http://test'))))

    @asynccontextmanager
    async def generator():
        yield client

    monkeypatch.setattr(api, 'generator_client', generator)
    owner, run_id = SimpleNamespace(user_id=uuid4()), uuid4()
    assert (await api.screen_all_contacts(run_id, request, owner)) == data
    client.post.return_value = httpx.Response(429, request=httpx.Request('POST', 'http://test'))
    with pytest.raises(HTTPException) as busy:
        await api.screen_all_contacts(run_id, request, owner)
    assert busy.value.status_code == 429
    owner_check.side_effect = HTTPException(404, 'not found')
    client.post.reset_mock()
    with pytest.raises(HTTPException):
        await api.screen_all_contacts(run_id, request, owner)
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidate_positions_validate_response_and_ownership(monkeypatch):
    request = api.ContactPositionsRequest(positions_um=[(0, 0, 0), (10, 0, 0), (20, 0, 0)],
                                          clearance_um=1)
    _, _, data = example()
    data['configuration'] = request.model_dump(mode='json')
    data['potential_intersections'] = [{'body_id': 1, 'source_sha256': 'a' * 64,
                                        'contact_indices': [0, 2],
                                        'conservative_clearance_um': [.5, 9., -1.]}]
    assert api.valid_contact_screen(data, request, 'graph', 3)
    bad = {**data, 'potential_intersections': [
        {**data['potential_intersections'][0], 'contact_indices': [0]}]}
    assert not api.valid_contact_screen(bad, request, 'graph', 3)
    assert not api.valid_contact_screen({**data, 'manifest_sha256': 'other'}, request, 'graph', 3)
    owner_check = AsyncMock(return_value=('graph', 3))
    monkeypatch.setattr(api, 'owned_spatial_graph', owner_check)
    client = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(
        200, json=data, request=httpx.Request('POST', 'http://test'))))

    @asynccontextmanager
    async def generator():
        yield client

    monkeypatch.setattr(api, 'generator_client', generator)
    owner, run_id = SimpleNamespace(user_id=uuid4()), uuid4()
    assert await api.screen_contact_positions(run_id, request, owner) == data
    assert client.post.await_args.args[0] == '/v1/connectome/contact-positions'
    client.post.return_value = httpx.Response(200, json=bad,
                                             request=httpx.Request('POST', 'http://test'))
    with pytest.raises(HTTPException) as mismatch:
        await api.screen_contact_positions(run_id, request, owner)
    assert mismatch.value.status_code == 409
    owner_check.side_effect = HTTPException(404, 'not found')
    client.post.reset_mock()
    with pytest.raises(HTTPException):
        await api.screen_contact_positions(run_id, request, owner)
    client.post.assert_not_awaited()
