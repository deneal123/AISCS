"""Post-processing hooks for agent pipeline."""

from __future__ import annotations


def run_post_response_hooks(
    *,
    user_id: int | str | None,
    thread_id: str,
    user_input: str,
    logger,
) -> None:
    """Execute non-blocking post-response hooks.

    Извлечение фактов в память НАМЕРЕННО убрано отсюда: оно выполняется единым
    пост-тёрновым вызовом в воркере (chat_worker_tasks). Раньше факты
    извлекались в ДВУХ местах на каждый ход (здесь по сообщению пользователя и в
    воркере по полному ходу) — это плодило near-duplicate факты («Данил» и
    «Пользователь зовут Данил») и удваивало LLM-вызовы.
    """
    return None
