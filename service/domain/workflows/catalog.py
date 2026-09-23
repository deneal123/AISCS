"""Autonomous workflow-catalog index and retrieval.

PostgreSQL in backend is the source of truth.  This module owns only the isolated
Qdrant projection used during a run: vectors plus non-sensitive execution fields.
It never stores a request text in a Qdrant payload and every read fails open to the
normal router/decomposition path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from service.domain.capabilities.agent_spec import COST_CHEAP, COST_CLASSES
from service.domain.capabilities.workflow_spec import WorkflowSpec, WorkflowStep
from service.domain.tools.vector_store import _embed_with_dim
from service.events import AgentEvent, EventType
from service.settings import config
from service.shared.agent_settings import runtime_settings

logger = logging.getLogger(__name__)

_ACTIVE_STATES = {"active", "pinned"}
_ROUTE_PREFIX = "workflow_catalog:"


def _collection() -> str:
    return str(
        runtime_settings.get_agents(
            "workflow_catalog_collection", config.agents.workflow_catalog_collection
        )
        or "gpthub_workflow_catalog"
    )


def _base() -> str:
    return (config.agents.qdrant_url or "").rstrip("/")


def enabled() -> bool:
    return bool(
        runtime_settings.get_agents(
            "workflow_catalog_enabled", config.agents.workflow_catalog_enabled
        )
        and _base()
    )


@dataclass(frozen=True, slots=True)
class CatalogWorkflow:
    workflow_id: str
    version: int
    name: str
    label_ru: str
    steps: tuple[str, ...]
    cost_class: str
    quality_score: float
    reuse_score: float
    state: str
    semantic_similarity: float
    rank: float


def route_override(candidate: CatalogWorkflow) -> str:
    """Opaque existing-confirmation value; it is always revalidated on the next run."""
    return f"{_ROUTE_PREFIX}{candidate.workflow_id}:{candidate.version}"


def requested_route(value: str | None) -> tuple[str, int] | None:
    raw = str(value or "")
    if not raw.startswith(_ROUTE_PREFIX):
        return None
    workflow_id, separator, version = raw.removeprefix(_ROUTE_PREFIX).rpartition(":")
    if not separator or not workflow_id:
        return None
    try:
        return workflow_id, int(version)
    except ValueError:
        return None


def confirmed_candidate(
    candidates: list[CatalogWorkflow], value: str | None
) -> CatalogWorkflow | None:
    requested = requested_route(value)
    if requested is None:
        return None
    return next(
        (
            candidate
            for candidate in candidates
            if (candidate.workflow_id, candidate.version) == requested
        ),
        None,
    )


def execution_event(candidate: CatalogWorkflow, *, failed: bool) -> AgentEvent:
    """Safe external trace: no request, output, instructions, or Qdrant payload contents."""
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="router",
        data="Выполнен сохранённый сценарий",
        metadata={
            "kind": "workflow_execution",
            "workflow_execution": {
                "workflow_id": candidate.workflow_id,
                "version": candidate.version,
                "name": candidate.name,
                "cost_class": candidate.cost_class,
                "status": "failed" if failed else "succeeded",
            },
        },
    )


def confirmation_offer(candidate: CatalogWorkflow, _user_input: str) -> AgentEvent:
    """Use the existing confirmation UI without exposing the private catalog entry."""
    from service.domain.pipeline.auto_mode import offer_ttl_sec

    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="router",
        data="Доступен сценарий с повышенной стоимостью",
        metadata={
            "kind": "mode_offer",
            "mode_offer": {
                "mode": route_override(candidate),
                "label": "сценарий с повышенной стоимостью",
                "reason": "Для задачи найден подходящий ранее успешный сценарий.",
                "offered_at": datetime.now(UTC).isoformat(),
                "expires_in_sec": offer_ttl_sec(),
            },
        },
    )


def _score(value: Any) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


def rank_candidates(
    hits: list[dict[str, Any]], *, minimum_similarity: float
) -> list[CatalogWorkflow]:
    """Validate Qdrant hits and rank the top candidates with the published formula."""
    ranked: list[CatalogWorkflow] = []
    for hit in hits:
        payload = hit.get("payload") if isinstance(hit, dict) else None
        if not isinstance(payload, dict):
            continue
        similarity = _score(hit.get("score"))
        if similarity < minimum_similarity or str(payload.get("state") or "") not in _ACTIVE_STATES:
            continue
        steps = payload.get("steps")
        if (
            not isinstance(steps, list)
            or not steps
            or not all(isinstance(item, str) for item in steps)
        ):
            continue
        cost_class = str(payload.get("cost_class") or COST_CHEAP)
        if cost_class not in COST_CLASSES:
            continue
        workflow_id = str(payload.get("workflow_id") or "")
        name = str(payload.get("name") or "")
        if not workflow_id or not name:
            continue
        quality = _score(payload.get("quality_score"))
        reuse = _score(payload.get("reuse_score"))
        ranked.append(
            CatalogWorkflow(
                workflow_id=workflow_id,
                version=int(payload.get("version") or 1),
                name=name,
                label_ru=str(payload.get("label_ru") or name),
                steps=tuple(steps),
                cost_class=cost_class,
                quality_score=quality,
                reuse_score=reuse,
                state=str(payload.get("state")),
                semantic_similarity=similarity,
                rank=0.70 * similarity + 0.20 * quality + 0.10 * reuse,
            )
        )
    return sorted(ranked, key=lambda item: (-item.rank, item.workflow_id, item.version))


async def _collection_ready(client: httpx.AsyncClient, *, dim: int, write: bool) -> bool:
    response = await client.get(f"{_base()}/collections/{_collection()}")
    if response.status_code == 404:
        if not write:
            return False
        created = await client.put(
            f"{_base()}/collections/{_collection()}",
            json={"vectors": {"size": int(dim), "distance": "Cosine"}},
        )
        return created.status_code < 400
    if response.status_code >= 400:
        return False
    try:
        params = ((response.json() or {}).get("result") or {}).get("config", {}).get("params", {})
        size = (params.get("vectors") or {}).get("size")
    except (AttributeError, TypeError, ValueError):
        return False
    return int(size) == int(dim)


async def retrieve(query: str) -> list[CatalogWorkflow]:
    """Return at most five safe catalog candidates, or no candidates on any failure."""
    if not enabled() or not str(query or "").strip():
        return []
    try:
        vectors, dim, _ = await _embed_with_dim([query])
        top_k = min(
            max(
                int(
                    runtime_settings.get_agents(
                        "workflow_catalog_top_k", config.agents.workflow_catalog_top_k
                    )
                    or 5
                ),
                1,
            ),
            5,
        )
        minimum = _score(
            runtime_settings.get_agents(
                "workflow_catalog_min_similarity", config.agents.workflow_catalog_min_similarity
            )
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            if not await _collection_ready(client, dim=dim, write=False):
                return []
            response = await client.post(
                f"{_base()}/collections/{_collection()}/points/search",
                json={
                    "vector": vectors[0],
                    "limit": top_k,
                    "with_payload": True,
                    "filter": {
                        "must": [{"key": "state", "match": {"any": sorted(_ACTIVE_STATES)}}]
                    },
                },
            )
        if response.status_code >= 400:
            return []
        hits = (response.json() or {}).get("result") or []
        return rank_candidates(hits if isinstance(hits, list) else [], minimum_similarity=minimum)[
            :top_k
        ]
    except Exception:  # noqa: BLE001 - retrieval is an optimization before decomposition
        logger.info(
            "workflow catalog retrieval unavailable",
            extra={"failure_code": "unavailable"},
        )
        return []


def to_workflow_spec(candidate: CatalogWorkflow) -> WorkflowSpec | None:
    """Revalidate every recorded step against the current local capability registry."""
    from service.domain.capabilities.runtime import get_static_catalog
    from service.domain.run_context import current_execution

    execution = current_execution()
    agents = (
        execution.capabilities.static.agents
        if execution is not None
        else get_static_catalog().agents
    )
    if any(step not in agents for step in candidate.steps):
        logger.warning("workflow catalog record %s has an unavailable step", candidate.workflow_id)
        return None
    actual_cost = _worst_cost(candidate.steps, agents)
    return WorkflowSpec(
        name=candidate.name,
        label_ru=candidate.label_ru,
        steps=tuple(
            WorkflowStep(agent=step, instruction="{user_input}") for step in candidate.steps
        ),
        cost_class=actual_cost,
        confirm_by_default=actual_cost != COST_CHEAP,
    )


def _worst_cost(steps: tuple[str, ...], agents: dict[str, Any]) -> str:
    worst = 0
    for step in steps:
        cost = str(getattr(agents[step], "cost_class", COST_CHEAP))
        worst = max(worst, COST_CLASSES.index(cost) if cost in COST_CLASSES else 0)
    return COST_CLASSES[worst]


async def upsert(
    *,
    point_id: str,
    workflow_id: str,
    version: int,
    name: str,
    label_ru: str,
    steps: list[str],
    cost_class: str,
    state: str,
    quality_score: float,
    reuse_score: float,
    request_text: str,
) -> bool:
    """Project one backend outbox row to Qdrant without retaining its request text."""
    if not enabled() or not request_text.strip() or not steps:
        return False
    try:
        vectors, dim, is_primary = await _embed_with_dim([request_text])
        async with httpx.AsyncClient(timeout=30.0) as client:
            if not await _collection_ready(client, dim=dim, write=True):
                if not is_primary:
                    return False
                await client.delete(f"{_base()}/collections/{_collection()}")
                if not await _collection_ready(client, dim=dim, write=True):
                    return False
            response = await client.put(
                f"{_base()}/collections/{_collection()}/points",
                params={"wait": "true"},
                json={
                    "points": [
                        {
                            "id": point_id,
                            "vector": vectors[0],
                            "payload": {
                                "workflow_id": workflow_id,
                                "version": int(version),
                                "name": name,
                                "label_ru": label_ru,
                                "steps": list(steps),
                                "cost_class": cost_class,
                                "state": state,
                                "quality_score": _score(quality_score),
                                "reuse_score": _score(reuse_score),
                            },
                        }
                    ]
                },
            )
        return response.status_code < 400
    except Exception:  # noqa: BLE001 - backend outbox retries transient failures
        logger.warning("workflow catalog index update failed code=unavailable")
        return False


async def delete(point_id: str) -> bool:
    """Delete an obsolete projection.  The backend keeps and retries its outbox row."""
    if not enabled() or not point_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{_base()}/collections/{_collection()}/points/delete",
                params={"wait": "true"},
                json={"points": [point_id]},
            )
        return response.status_code < 400
    except Exception:  # noqa: BLE001
        logger.warning("workflow catalog index delete failed code=unavailable")
        return False
