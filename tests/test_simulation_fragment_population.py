import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from service.services.simulations import api
from service.services.simulations.manifests.fragment_population_manifest import (
    InvalidFragmentPopulationManifest,
    validate_fragment_population_manifest,
    validate_fragment_population_preview,
)


def test_fragment_manifest_and_preview_reject_misrepresentation():
    names = [
        "signals.npz",
        "model.json",
        "source-provenance.jsonl",
        "fragment-population-preview.json",
    ]
    manifest = {
        "kind": "experimental-fragment-population",
        "configuration_sha256": "a" * 64,
        "graph_sha256": "b" * 64,
        "coverage": "explicitly supplied sources only; not a full-network physical recording",
        "files": [{"name": name, "bytes": 10, "sha256": "c" * 64} for name in names],
    }
    validate_fragment_population_manifest(
        manifest, configuration_sha256="a" * 64, graph_sha256="b" * 64
    )
    validate_fragment_population_manifest(
        {**manifest, "files": [*manifest["files"],
                               {"name": "fragment-events.bin", "bytes": 10, "sha256": "d" * 64}]},
        configuration_sha256="a" * 64, graph_sha256="b" * 64,
    )
    response = {"name": "fragment-response.npz", "bytes": 10, "sha256": "e" * 64}
    events = {"name": "fragment-events.bin", "bytes": 10, "sha256": "d" * 64}
    validate_fragment_population_manifest(
        {**manifest, "files": [*manifest["files"], events, response]},
        configuration_sha256="a" * 64, graph_sha256="b" * 64,
    )
    binary = {"name": "fragment-response.bin", "bytes": 10, "sha256": "f" * 64}
    validate_fragment_population_manifest(
        {**manifest, "files": [*manifest["files"], events, response, binary]},
        configuration_sha256="a" * 64, graph_sha256="b" * 64,
    )
    sparse = {"name": "fragment-delta.bin", "bytes": 10, "sha256": "a" * 64}
    validate_fragment_population_manifest(
        {**manifest, "files": [*manifest["files"], events, response, binary, sparse]},
        configuration_sha256="a" * 64, graph_sha256="b" * 64,
    )
    with pytest.raises(InvalidFragmentPopulationManifest):
        validate_fragment_population_manifest(
            {**manifest, "files": [*manifest["files"], events, response, sparse]},
            configuration_sha256="a" * 64, graph_sha256="b" * 64,
        )
    with pytest.raises(InvalidFragmentPopulationManifest):
        validate_fragment_population_manifest(
            {**manifest, "files": [*manifest["files"], response]},
            configuration_sha256="a" * 64, graph_sha256="b" * 64,
        )
    with pytest.raises(InvalidFragmentPopulationManifest):
        validate_fragment_population_manifest(
            {**manifest, "coverage": "full network"},
            configuration_sha256="a" * 64,
            graph_sha256="b" * 64,
        )
    config = {"source_ids": [1, 2], "simulation": {"duration_ms": 2, "dt_ms": 1}}
    preview = {
        "samples": 3,
        "shown_samples": 3,
        "stimulus_boundaries_preserved": True,
        "time_ms": [0, 1, 2],
        "neural_uv": [0, 0, 0],
        "total_uv": [0, 0, 0],
        "stimulus_fraction": [0, 1, 0],
        "network_spikes_by_ms": [0, 1, 0],
        "source_cells": 2,
        "edge_event_count": 1,
        "units": {"time_ms": "ms", "neural_uv": "µV", "total_uv": "µV"},
        "limitations": [
            "Расчёт ограничен выбранными клетками.",
            "Фрагменты и граф не имеют обратной связи.",
            "Параметры модели и расположение в теле не откалиброваны.",
            "Положение контактов относительно тканей и формы тела не проверено.",
        ],
    }
    validate_fragment_population_preview(preview, config)
    with pytest.raises(InvalidFragmentPopulationManifest):
        validate_fragment_population_preview({**preview, "source_cells": 166700}, config)
    with pytest.raises(InvalidFragmentPopulationManifest):
        validate_fragment_population_preview({**preview, "limitations": []}, config)
    partial_config = {**config, 'allow_partial_geometry': True}
    partial_preview = {**preview, 'unresolved_graph_pairs': 3, 'limitations': [
        *preview['limitations'], 'Не сопоставлены с отростками синапсы: 3; '
        'их события неизвестны и не включены в передачу.']}
    validate_fragment_population_preview(partial_preview, partial_config)
    with pytest.raises(InvalidFragmentPopulationManifest):
        validate_fragment_population_preview(
            {**partial_preview, 'limitations': preview['limitations']}, partial_config)
    with pytest.raises(InvalidFragmentPopulationManifest):
        validate_fragment_population_preview(partial_preview, config)


@pytest.mark.asyncio
@pytest.mark.parametrize("tampered", [False, True])
async def test_fragment_api_binds_validation_to_request(monkeypatch, tampered):
    requested = {"source_ids": [10, 20], "max_distance_um": 2}
    normalized = {"source_ids": [10, 21] if tampered else [10, 20], "max_distance_um": 2}
    digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    response = httpx.Response(
        200,
        json={"configuration": normalized, "configuration_sha256": digest},
        request=httpx.Request("POST", "http://g/test"),
    )
    post = AsyncMock(return_value=response)

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(post=post)

    monkeypatch.setattr(api, "generator_client", factory)
    create = AsyncMock(return_value={"id": "queued"})
    monkeypatch.setattr(api, "create_checked_run", create)
    payload = api.RunCreate(request_id=uuid4(), configuration=requested)
    if tampered:
        with pytest.raises(HTTPException) as error:
            await api.create_fragment_population_run(payload, SimpleNamespace(user_id=uuid4()))
        assert error.value.status_code == 503
        create.assert_not_awaited()
    else:
        assert await api.create_fragment_population_run(
            payload, SimpleNamespace(user_id=uuid4())
        ) == {"id": "queued"}
        create.assert_awaited_once()
    assert post.await_args.args[0] == "/v1/fragment-population-validate"


@pytest.mark.asyncio
async def test_fragment_parent_must_be_owned_compatible_graph(monkeypatch):
    @asynccontextmanager
    async def session():
        yield object()

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    source = AsyncMock(side_effect=api.ReplaySourceUnavailable('source_graph_mismatch'))
    monkeypatch.setattr(api, 'owned_replay_source', source)
    user_id, parent_id = uuid4(), uuid4()
    payload = api.RunCreate(request_id=uuid4(), parent_run_id=parent_id,
                            configuration={'graph_manifest_sha256': 'a' * 64})
    with pytest.raises(HTTPException) as error:
        await api.create_fragment_population_run(payload, SimpleNamespace(user_id=user_id))
    assert error.value.status_code == 404
    source.assert_awaited_once()
    assert source.await_args.args[1:] == (user_id, parent_id, 'a' * 64)
