"""Сравнение извлечения контракта на синтетике: без журнала, записи и исполнения."""

import asyncio
import json
import os
import sys
from types import SimpleNamespace

CASES = (
    {
        "name": "clear_script",
        "goal": (
            "Создай в корне hello_world.py. Скрипт должен вывести ровно hello world "
            "и перевод строки. Сохрани и прочитай файл, затем запусти для проверки вывода. "
            "Не устанавливай зависимости."
        ),
        "kind": "change",
        "criterion_kind": "file",
        "target": "hello_world.py",
        "clarify": False,
    },
    {
        "name": "read_without_write",
        "goal": "Прочитай config.json и объясни его структуру. Ничего не меняй.",
        "kind": "analysis",
        "criterion_kind": "read",
        "target": "config.json",
        "clarify": False,
    },
    {
        "name": "missing_desired_limit",
        "goal": "В limits.py замени число в MAX_USERS на желаемый мной лимит.",
        "kind": "change",
        "criterion_kind": "file",
        "target": "limits.py",
        "clarify": True,
    },
)


def concise_messages(admission):
    return [
        {
            "role": "system",
            "content": (
                "Определи требуемый результат задачи IDE и вызови submit_task_contract. "
                "Это предложение критериев, не выполнение. Не выдавай прав и не подтверждай успех. "
                "Создание/изменение файла: kind=change, критерий kind=file и точное имя файла. "
                "Только чтение: kind=analysis, критерий kind=read. Пути относительные. "
                "Запуск и проверку добавит сервер; не дублируй их и не используй verify_project. "
                "Если имя файла и требуемый результат заданы, "
                "needs_clarification=false и question=''. "
                "Как написать код или прочитать доступный файл, решает агент, не пользователь. "
                "Если отсутствует существенное решение пользователя, needs_clarification=true "
                "и один конкретный вопрос по-русски. Не выдумывай желаемые пользователем значения. "
                "Пример: 'Создай note.txt с текстом привет' — false. "
                "Пример: 'Поставь в limits.py желаемый мной лимит' без числа — true, спроси число. "
                "Каждый критерий: criterion_id (латиница), kind, target. "
                f"Разрешённые сервером действия: {','.join(admission.actions)}."
            ),
        },
        {"role": "user", "content": "Запрос: " + admission.goal},
    ]


def guided_messages(admission):
    messages = concise_messages(admission)
    messages[0]["content"] += (
        "\nОбразцы ответа функции, только примеры формы, не текущая задача:\n"
        "Запрос: Создай note.txt с текстом привет.\n"
        '{"kind":"change","criteria":[{"criterion_id":"note","kind":"file",'
        '"target":"note.txt"}],"needs_clarification":false,"question":""}\n'
        "Запрос: Прочитай README.md и объясни содержание, без изменений.\n"
        '{"kind":"analysis","criteria":[{"criterion_id":"source","kind":"read",'
        '"target":"README.md"}],"needs_clarification":false,"question":""}\n'
        "Запрос: В settings.py установи желаемый мной таймаут. Значение не указано.\n"
        '{"kind":"change","criteria":[{"criterion_id":"config","kind":"file",'
        '"target":"settings.py"}],"needs_clarification":true,'
        '"question":"Какое значение таймаута установить?"}\n'
        "Пути и значения в образцах не относятся к текущему запросу. "
        "Текущий запрос — последнее сообщение пользователя."
    )
    return messages


def selected_builders(profile, baseline):
    builders = {"baseline": baseline, "concise": concise_messages, "guided": guided_messages}
    if profile == "all":
        return tuple(builders.items())
    if profile == "both":
        return tuple((name, builders[name]) for name in ("baseline", "concise"))
    if profile not in builders:
        raise ValueError("admission_profile_invalid")
    return ((profile, builders[profile]),)


async def _exercise(key, selected_profile):
    os.environ["AGENTS__LOCAL_API_KEY"] = key
    os.environ["AGENTS__LOCAL_BASE_URL"] = "http://local-llm:8080/v1"
    from service.application.harness.proposal import (
        CONTRACT_FUNCTION,
        contract_messages,
        contract_tool,
        parse_proposal,
        repair_messages,
        response_arguments,
    )
    from service.domain.client import create_chat_completion
    from service.domain.client.providers.local import MODEL_ID
    from service.domain.execution.context import PrivateRunResources, use_run_execution
    from service.domain.execution.model import invoke_model_call
    from service.domain.llm_response import first_message_content

    rows = []
    for profile, message_builder in selected_builders(selected_profile, contract_messages):
        for case in CASES:
            admission = SimpleNamespace(
                surface="ide", actions=("read", "write", "exec"), goal=case["goal"]
            )
            messages = message_builder(admission)
            with use_run_execution(PrivateRunResources()) as execution:
                for attempt in range(2):
                    result = await invoke_model_call(
                        create_chat_completion,
                        execution=execution,
                        model=MODEL_ID,
                        kind="meta_usage",
                        pin_provider="local",
                        temperature=0.1,
                        max_tokens=512,
                        messages=messages,
                        tools=[contract_tool(admission)],
                        tool_choice={"type": "function", "function": {"name": CONTRACT_FUNCTION}},
                    )
                    row = {
                        "profile": profile,
                        "case": case["name"],
                        "attempt": attempt,
                        "tokens": result.usage.total,
                        "finish_reason": result.finish_reason,
                    }
                    content = first_message_content(result.response)
                    valid = False
                    try:
                        content = response_arguments(result.response)
                        row["synthetic_arguments"] = json.loads(content)
                        proposal = parse_proposal(content, admission)
                        valid = True
                        row.update(
                            proposal=proposal.model_dump(mode="json"),
                            matched=(
                                proposal.kind == case["kind"]
                                and proposal.needs_clarification == case["clarify"]
                                and {(item.kind, item.target) for item in proposal.criteria}
                                == {(case["criterion_kind"], case["target"])}
                            ),
                        )
                    except ValueError as error:
                        row.update(matched=False, failure="proposal_protocol_invalid")
                        messages = repair_messages(messages, content, error=error)
                    assert len(execution.usage.receipts) == attempt + 1, "usage_receipt_invalid"
                    rows.append(row)
                    if valid:
                        break
    final = {(row["profile"], row["case"]): row for row in rows}
    return {
        "model_calls": len(rows),
        "matched_cases": sum(bool(row["matched"]) for row in final.values()),
        "case_count": len(final),
        "synthetic_read_only": True,
        "adopted": False,
        "results": rows,
    }


async def exercise(key, selected_profile="both"):
    async with asyncio.timeout(300):
        return await _exercise(key, selected_profile)


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        print(
            json.dumps(
                asyncio.run(exercise(request["key"], request.get("admission_profile", "both"))),
                ensure_ascii=False,
            )
        )
    except Exception as error:
        print(json.dumps({"failure": "admission_probe_failed", "category": type(error).__name__}))
        raise SystemExit(1) from None
