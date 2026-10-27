from __future__ import annotations


def prompt_budget_per_run() -> int:
    """Клиентский предел для legacy-чата без backend-owned admission."""
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    value = runtime_settings.get_agents(
        "chat_max_prompt_tokens_per_run",
        config.agents.chat_max_prompt_tokens_per_run,
    )
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 40_000


def prompt_budget_for_execution(execution, *, legacy_limit: int) -> int:
    """Durable-задача использует выданный admission, а не второй денежный лимит.

    Backend ограничивает каждый grant, общий расход, число вызовов и активное время.
    Здесь остаётся только конечная граница суммарного prompt по оставшимся model calls;
    это не разрешение увеличить credits или tokens одного запроса. Успешные receipts
    учитываются после восстановления; unknown/allocated всё равно блокирует сервер.
    """
    client = execution.harness
    current = client.current if client is not None else None
    if current is None or current.state is None:
        return legacy_limit
    admission = current.admission
    remaining = max(0, admission.paid_call_limit - len(current.usage))
    # В legacy exceeds_prompt_budget значение0 означает отсутствие ограничения.
    # При исчерпании разрешений нужен запрет следующего prompt, а не unlimited.
    return max(1, admission.prompt_limit * remaining)
