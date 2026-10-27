"""Legacy40k не подменяет согласованный бюджет durable-задачи; новый лимит конечен."""

from types import SimpleNamespace

from service.domain.runners.prompt_budget import prompt_budget_for_execution


def execution(*, calls=48, used=0, state=True, prompt=32768):
    return SimpleNamespace(
        harness=SimpleNamespace(
            current=SimpleNamespace(
                state=object() if state else None,
                admission=SimpleNamespace(
                    paid_call_limit=calls, prompt_limit=prompt, credit_limit=100
                ),
                usage=[object() for _ in range(used)],
            )
        )
    )


def test_legacy_budget_is_unchanged_without_sealed_admission():
    assert prompt_budget_for_execution(SimpleNamespace(harness=None), legacy_limit=40000) == 40000
    assert prompt_budget_for_execution(execution(state=False), legacy_limit=1000) == 1000


def test_durable_profile_uses_existing_server_limits_not_tool_names():
    run = execution(calls=48, used=2)
    assert prompt_budget_for_execution(run, legacy_limit=40000) == 46 * 32768
    assert run.harness.current.admission.credit_limit == 100
    assert run.harness.current.admission.paid_call_limit == 48


def test_resumed_receipts_reduce_the_same_task_bound():
    assert (
        prompt_budget_for_execution(execution(calls=4, used=3, prompt=1000), legacy_limit=40000)
        == 1000
    )
    assert prompt_budget_for_execution(execution(calls=4, used=4), legacy_limit=40000) == 1
