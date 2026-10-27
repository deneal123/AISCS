"""Контрастный model-double: без обратной связи пытается преждевременно закончить."""

PREMATURE = "НЕПОДТВЕРЖДЁННЫЙ УСПЕХ: скрипт уже создан и проверен."


def decide(function, messages, functions):
    names = {item["name"] for item in functions}
    guided = any(
        message.get("role") == "user"
        and str(message.get("content", "")).startswith("[harness:verification-repair:")
        for message in messages
    )
    if not guided or "ide_finish_task" in names:
        return ("ide_finish_task", {"summary": PREMATURE, "outcome": "changed"}), PREMATURE
    return function, ""
