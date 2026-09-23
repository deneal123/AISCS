"""Autonomous workflow catalog: ranking, safety boundary, and confirmation revalidation."""

from __future__ import annotations

import pytest

from service.domain.capabilities.agent_spec import COST_CHEAP, COST_EXPENSIVE
from service.domain.capabilities.workflow_spec import WorkflowSpec, WorkflowStep
from service.domain.pipeline import workflow_catalog_selection
from service.domain.workflows import catalog


def _hit(*, workflow_id: str, score: float, quality: float, reuse: float, state: str = "active"):
    return {
        "score": score,
        "payload": {
            "workflow_id": workflow_id,
            "version": 1,
            "name": f"workflow_{workflow_id}",
            "label_ru": "Сохранённый сценарий",
            "steps": ["general", "web_search"],
            "cost_class": "paid",
            "quality_score": quality,
            "reuse_score": reuse,
            "state": state,
        },
    }


def test_ranking_uses_similarity_quality_and_reuse_without_request_payload():
    ranked = catalog.rank_candidates(
        [
            _hit(workflow_id="semantic", score=0.90, quality=0.20, reuse=0.10),
            _hit(workflow_id="quality", score=0.82, quality=1.0, reuse=1.0),
        ],
        minimum_similarity=0.78,
    )

    assert [candidate.workflow_id for candidate in ranked] == ["quality", "semantic"]
    assert ranked[0].rank == pytest.approx(0.874)


def test_ranking_rejects_low_similarity_pruned_and_malformed_records():
    ranked = catalog.rank_candidates(
        [
            _hit(workflow_id="low", score=0.779, quality=1.0, reuse=1.0),
            _hit(workflow_id="pruned", score=0.99, quality=1.0, reuse=1.0, state="pruned"),
            {"score": 0.99, "payload": {"workflow_id": "broken", "steps": []}},
        ],
        minimum_similarity=0.78,
    )

    assert ranked == []


def test_confirmation_route_is_opaque_and_must_match_the_current_candidate():
    candidate = catalog.rank_candidates(
        [_hit(workflow_id="id-a", score=0.9, quality=0.8, reuse=0.4)], minimum_similarity=0.78
    )[0]

    assert catalog.confirmed_candidate([candidate], catalog.route_override(candidate)) == candidate
    assert catalog.confirmed_candidate([candidate], "workflow_catalog:id-a:2") is None
    assert catalog.confirmed_candidate([candidate], "deep_research") is None


def test_catalog_confirmation_offer_does_not_contain_the_exact_request():
    candidate = catalog.rank_candidates(
        [_hit(workflow_id="id-a", score=0.9, quality=0.8, reuse=0.4)], minimum_similarity=0.78
    )[0]

    event = catalog.confirmation_offer(candidate, "exact private request")

    assert "prompt" not in event.metadata["mode_offer"]
    assert "exact private request" not in str(event.metadata)


@pytest.mark.asyncio
async def test_index_payload_never_contains_the_exact_request(monkeypatch):
    seen: list[dict] = []

    class _Response:
        def __init__(self, status_code: int, body=None):
            self.status_code = status_code
            self._body = body or {}

        def json(self):
            return self._body

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return _Response(404)

        async def put(self, _url, **kwargs):
            if "points" in (kwargs.get("json") or {}):
                seen.append(kwargs["json"]["points"][0]["payload"])
            return _Response(200)

    async def _embed(_texts):
        return [[0.1, 0.2]], 2, True

    monkeypatch.setattr(catalog, "enabled", lambda: True)
    monkeypatch.setattr(catalog, "_embed_with_dim", _embed)
    monkeypatch.setattr(catalog.httpx, "AsyncClient", lambda **_kwargs: _Client())

    assert await catalog.upsert(
        point_id="point-1",
        workflow_id="workflow-1",
        version=1,
        name="workflow_1",
        label_ru="Сохранённый сценарий",
        steps=["general", "web_search"],
        cost_class="paid",
        state="active",
        quality_score=0.8,
        reuse_score=0.4,
        request_text="точный закрытый запрос пользователя",
    )
    assert seen and "request_text" not in seen[0]
    assert "точный закрытый запрос пользователя" not in str(seen[0])


def _candidate() -> catalog.CatalogWorkflow:
    return catalog.CatalogWorkflow(
        workflow_id="s16-catalog",
        version=3,
        name="s16_catalog_workflow",
        label_ru="Сохранённый сценарий",
        steps=("general",),
        cost_class=COST_CHEAP,
        quality_score=0.9,
        reuse_score=0.5,
        state="active",
        semantic_similarity=0.9,
        rank=0.82,
    )


@pytest.mark.asyncio
async def test_quality_gate_catalog_selection_revalidates_cost_and_fails_open(monkeypatch):
    """S16 uses the actual selection seam, not a catalog-only ranking double."""
    candidate = _candidate()
    expensive = WorkflowSpec(
        name=candidate.name,
        label_ru=candidate.label_ru,
        steps=(WorkflowStep(agent="general", instruction="{user_input}"),),
        cost_class=COST_EXPENSIVE,
        confirm_by_default=True,
    )

    async def retrieve(_query: str):
        return [candidate]

    monkeypatch.setattr(catalog, "retrieve", retrieve)
    monkeypatch.setattr(catalog, "to_workflow_spec", lambda _candidate: expensive)
    private_input = "synthetic-request-must-not-cross-catalog-trace"

    offered = await workflow_catalog_selection.select_catalog_workflow(
        user_input=private_input,
        route_override=None,
        resolved_category="general",
    )
    assert offered.blocked_for_confirmation is True
    assert offered.subtasks is None
    assert offered.events[0].metadata["kind"] == "mode_offer"
    assert private_input not in str(offered.events[0].metadata)

    confirmed = await workflow_catalog_selection.select_catalog_workflow(
        user_input=private_input,
        route_override=catalog.route_override(candidate),
        resolved_category="general",
    )
    assert confirmed.candidate is not None
    assert confirmed.candidate.cost_class == COST_EXPENSIVE
    assert [task.category for task in confirmed.subtasks or []] == ["general"]

    async def unavailable(_query: str):
        return []

    monkeypatch.setattr(catalog, "retrieve", unavailable)
    fallback = await workflow_catalog_selection.select_catalog_workflow(
        user_input=private_input,
        route_override=catalog.route_override(candidate),
        resolved_category="general",
    )
    assert fallback.subtasks is None and fallback.events == []
    assert fallback.route_override is None and fallback.resolved_category is None
