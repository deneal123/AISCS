"""Backend-only capability; older workers never accidentally advertise a pause."""

from uuid import UUID


def apply_human_question_context(execution) -> bool:
    execution.policy.set_flag("human_questions_enabled", False)
    ref = execution.resources.workspace_ref or {}
    if ref.get("human_questions_enabled") is not True:
        return False
    ide, document = ref.get("ide_context"), ref.get("document_context")
    if isinstance(ide, dict) == isinstance(document, dict):
        return False
    target = ide if isinstance(ide, dict) else document
    try:
        UUID(str(target.get("repository_id" if isinstance(ide, dict) else "project_id")))
    except (ValueError, TypeError):
        return False
    snapshot = execution.provider_snapshot
    # Все поддерживаемые IDE/PDF-провайдеры используют общий цикл, включая local.
    # Неизвестный runtime исключён; серверный допуск выше остаётся обязательным.
    if snapshot is None or snapshot.active_provider not in {
        "mws",
        "openrouter",
        "gigachat",
        "routerai",
        "openai",
        "local",
    }:
        return False
    execution.policy.set_flag("human_questions_enabled", True)
    return True
