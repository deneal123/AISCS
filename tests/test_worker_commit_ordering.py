"""Ход диалога коммитится ДО публикации agent_reply (аудит T3.3).

Раньше publish("agent_reply") шёл до session.commit(): при сбое финального commit юзер
уже видел «готово», а в БД — откат + рефанд + «прервана» после reload (расхождение
экран/БД). Теперь публикуем только durably-сохранённое.
"""

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import service.services.chat.infrastructure.chat_worker_tasks as cwt
from service.services.chat.infrastructure.chat_worker import publication, run_execution

_RUN_QUALITY_MANIFEST = Path(__file__).resolve().parent / "fixtures" / "run_quality_s16.json"


def test_commit_precedes_agent_reply_publish():
    src = inspect.getsource(run_execution._finalize_success)
    commit_at = src.index("await session.commit()")
    reply_at = src.index("await hooks.publish_committed_turn(")
    assert commit_at < reply_at, "agent_reply публикуется ДО commit"


def test_post_commit_block_is_best_effort():
    """Публикация/память после commit не должны флипать в FAILURE/refund."""
    src = inspect.getsource(run_execution._finalize_success)
    commit_at = src.index("await session.commit()")
    tail = src[commit_at:]
    assert "await hooks.publish_committed_turn(" in tail
    publication_source = inspect.getsource(publication.publish_committed_turn)
    # После commit есть свой try/except (иначе post-commit сбой ушёл бы в общий except).
    assert "try:" in publication_source and "except Exception:" in publication_source
    assert "post-commit publish/memory failed" in publication_source


@pytest.mark.asyncio
async def test_completed_job_redelivery_reuses_one_durable_billing_envelope(monkeypatch) -> None:
    """A crash/redelivery must return the committed envelope without executing or charging again."""
    from service.infrastructure.agents_client import engine_factory
    from service.models.key_value import ProcessingStatus
    from service.services.jobs.persistence import job_repository as job_repository_module

    manifest = json.loads(_RUN_QUALITY_MANIFEST.read_text(encoding="utf-8"))
    expected = next(
        item for item in manifest["scenarios"] if item["id"] == "crash_redelivery_single_billing"
    )
    durable_usage = {
        "per_call_usage": [
            {
                "provider": "scripted",
                "model": "golden",
                "prompt_tokens": 1,
                "completion_tokens": 1,
            }
        ]
    }
    durable_job = SimpleNamespace(
        status=ProcessingStatus.SUCCESS,
        payload={"reply": "durable reply", "metadata": durable_usage},
    )
    observed_order: list[str] = []
    charged_on_redelivery = 0
    provider_calls_on_redelivery = 0

    class _JobRepository:
        def __init__(self, _connector) -> None:
            pass

        async def fetch_job_by_id(self, _job_id, _user_id, *, session):
            del session
            observed_order.append("durable_result")
            return durable_job

    class _Session:
        pass

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *_exc) -> bool:
            return False

    class _Connector:
        def get_session_context(self):
            return _SessionContext()

    class _Dependencies:
        def create_pg_connector(self, _config):
            return _Connector()

        def create_redis_client(self, _config):
            return None

    class _Publisher:
        def __init__(self, **_kwargs) -> None:
            self.published: list[dict] = []

        def publish_payload(self, payload: dict) -> bool:
            self.published.append(payload)
            return True

        def close(self) -> None:
            pass

    publisher = _Publisher()
    real_redelivery_short_circuit = cwt._redelivery_short_circuit

    async def _observed_redelivery(*args, **kwargs):
        result = await real_redelivery_short_circuit(*args, **kwargs)
        if result is not None:
            observed_order.append("redelivery_short_circuit")
        return result

    async def _unexpected_charge(*_args, **_kwargs):
        nonlocal charged_on_redelivery
        charged_on_redelivery += 1
        raise AssertionError("redelivery reached the charging seam")

    def _unexpected_provider(*_args, **_kwargs):
        nonlocal provider_calls_on_redelivery
        provider_calls_on_redelivery += 1
        raise AssertionError("redelivery reached the provider seam")

    async def _no_provider_key_sync() -> None:
        return None

    monkeypatch.setattr(job_repository_module, "JobRepository", _JobRepository)
    monkeypatch.setattr(cwt, "_redelivery_short_circuit", _observed_redelivery)
    monkeypatch.setattr(cwt, "_bind_runtime_settings", lambda _connector: None)
    monkeypatch.setattr(cwt, "_sync_provider_keys", _no_provider_key_sync)
    monkeypatch.setattr(cwt, "_build_file_service", lambda *_args: object())
    monkeypatch.setattr(cwt, "WorkerStreamPublisherService", lambda **_kwargs: publisher)
    monkeypatch.setattr(cwt, "charge_and_describe", _unexpected_charge)
    monkeypatch.setattr(engine_factory, "select_agent_engine", _unexpected_provider)

    result = await cwt.process_agent_message_async(
        job_id=str(uuid4()),
        thread_id=str(uuid4()),
        text="synthetic",
        user_id=str(uuid4()),
        dependency_factory=_Dependencies(),
    )

    actual_counts = {
        "billing_envelopes": len(result["metadata"]["per_call_usage"]),
        "terminal_results": int(result["status"] == "success" and isinstance(result["reply"], str)),
        "redeliveries": observed_order.count("redelivery_short_circuit"),
        "redelivery_billing_envelopes": charged_on_redelivery,
    }
    actual_statuses = [result["status"], "redelivery_skipped"]
    actual_reasons = ["already_succeeded"]

    assert observed_order == expected["event_order"]
    assert actual_counts == expected["counts"]
    assert actual_statuses == expected["statuses"]
    assert actual_reasons == expected["reasons"]
    assert provider_calls_on_redelivery == expected["budgets"]["provider_calls_on_redelivery"]
    assert publisher.published == []
