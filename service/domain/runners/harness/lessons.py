"""Повторное использование принятого урока, не новой способности или evidence."""

from service.shared.harness_refinement import RefinementProposal

from .refinement import render_refinement


async def with_verified_lessons(messages, tools, execution):
    from service.settings import config

    client = execution.harness
    if not config.agents.harness_refinement_enabled or client is None:
        return messages
    if client.current.continuation.messages or execution.cancelled:
        return messages
    if client.current.continuation.provider is None:
        session = execution.provider_session
        if not session.pinned_provider or not session.pinned_model:
            return messages
        # До первого model checkpoint backend ещё не знает pin, выбранный при
        # admission. Пустой transcript фиксирует binding, но не расходует slot,
        # tool-round или repair и не превращается в replay исходного запроса.
        await client.checkpoint(execution, [], phase="model")
    response = await client.exchange(opcode="lessons")
    offered = {tool["function"]["name"] for tool in tools or []}
    for raw in response.get("lessons", [])[:3]:
        try:
            proposal = RefinementProposal.model_validate(raw)
        except ValueError:
            continue
        if any(tool.name not in offered for tool in proposal.tools):
            continue
        # Один короткий урок; полный transcript, вывод команды и operation IDs сюда
        # не попадают. Этот user turn сохраняется обычным checkpoint до inference.
        return [*messages, {"role": "user", "content": render_refinement(proposal)}]
    return messages
