from __future__ import annotations


def prompt_budget_per_run() -> int:
    """Read the sole automatic cost guard for one chat run."""
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
