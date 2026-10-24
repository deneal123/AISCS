"""Сравнение извлечения контракта на синтетике: без журнала, записи и исполнения."""

import asyncio
import json
import os
import sys
from copy import deepcopy
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

EXTRA_CASES = (
    {
        "name": "different_script",
        "goal": (
            "Создай subtract.py с функцией subtract(a, b), возвращающей a - b. "
            "Прочитай и проверь файл."
        ),
        "kind": "change",
        "criterion_kind": "file",
        "target": "subtract.py",
        "clarify": False,
    },
    {
        "name": "two_files",
        "goal": (
            "Создай emit_a.py и emit_b.py. Каждый скрипт выводит своё имя и перевод строки. "
            "Сохрани, прочитай и запусти оба. Не устанавливай зависимости."
        ),
        "kind": "change",
        "clarify": False,
        "expected_targets": (("file", "emit_a.py"), ("file", "emit_b.py")),
    },
)


def case_set(suite):
    if suite == "basic":
        return CASES
    if suite == "extended":
        return (*CASES, *EXTRA_CASES)
    raise ValueError("admission_suite_invalid")


def matches(proposal, case):
    targets = case.get("expected_targets") or ((case["criterion_kind"], case["target"]),)
    return (
        proposal.kind == case["kind"]
        and proposal.needs_clarification == case["clarify"]
        and len(proposal.criteria) == len(targets)
        and {(item.kind, item.target) for item in proposal.criteria} == set(targets)
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


def guided_messages(admission, *, workflow=False):
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
    )
    if workflow:
        messages[0]["content"] += (
            "Запрос: Создай worker.py, печатающий готово. "
            "Сохрани, прочитай и запусти его для проверки.\n"
            '{"kind":"change","criteria":[{"criterion_id":"worker","kind":"file",'
            '"target":"worker.py"}],"needs_clarification":false,"question":""}\n'
            "Чтение и запуск для проверки правки входят в серверную проверку файла, "
            "а не добавляют отдельные результаты. "
            "Каждый запрошенный файл остаётся отдельным file-критерием. "
        )
    messages[0]["content"] += (
        "Пути и значения в образцах не относятся к текущему запросу. "
        "Текущий запрос — последнее сообщение пользователя."
    )
    return messages


def decision_messages(admission):
    return [
        {
            "role": "system",
            "content": (
                "Составь контракт результата задачи IDE и вызови submit_task_contract. "
                "Не выполняй задачу и не объявляй успех.\n"
                "1. Сначала реши, отсутствует ли существенный выбор пользователя. "
                "Если пользователь просит своё желаемое значение, но его не указал, "
                "нужен needs_clarification=true и конкретный вопрос по-русски. "
                "Не подставляй своё значение. Если результат уже задан, используй false "
                "и пустой question. Чтение доступных файлов и выбор способа реализации "
                "не требуют вопроса.\n"
                "2. Только чтение без изменений: kind=analysis, критерии kind=read. "
                "Создание или изменение: kind=change, критерии kind=file.\n"
                "3. criteria — список результатов, а не шагов. Каждый запрошенный файл "
                "укажи ровно один раз, сохрани его имя в target. Пути относительные без ./ . "
                "Сохранение, чтение и запуск создаваемого файла относятся к его проверке, "
                "а не к дополнительным критериям. Для разных результатов используй разные "
                "criterion_id: строчная латиница, цифры, _ и -. Не используй verify_project. "
                "Не добавляй не запрошенные файлы и не убирай запрошенные. "
                f"Разрешённые действия сервера: {','.join(admission.actions)}."
            ),
        },
        {"role": "user", "content": "Запрос: " + admission.goal},
    ]


def candidate_tool(profile, original):
    tool = deepcopy(original)
    if profile in {"ordered", "decision_first"}:
        schema = tool["function"]["parameters"]
        order = ("needs_clarification", "question", "kind", "criteria")
        schema["properties"] = {name: schema["properties"][name] for name in order}
        schema["required"] = list(order)
    return tool


def selected_builders(profile, baseline):
    builders = {
        "baseline": baseline,
        "concise": concise_messages,
        "guided": guided_messages,
        "workflow_guided": lambda admission: guided_messages(admission, workflow=True),
        "ordered": baseline,
        "decision_first": decision_messages,
    }
    if profile == "all":
        return tuple((name, builders[name]) for name in ("baseline", "concise", "guided"))
    if profile == "both":
        return tuple((name, builders[name]) for name in ("baseline", "concise"))
    if profile not in builders:
        raise ValueError("admission_profile_invalid")
    return ((profile, builders[profile]),)


def sampling_parameters(mode):
    if mode == "runtime":
        # Как в seal_harness: sampling провайдера не переопределяется.
        return {"max_tokens": 2048}
    if mode == "diagnostic":
        return {"temperature": 0.1, "max_tokens": 512}
    raise ValueError("admission_sampling_invalid")


async def _exercise(key, selected_profile, suite, sampling):
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
        for case in case_set(suite):
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
                        **sampling_parameters(sampling),
                        messages=messages,
                        tools=[candidate_tool(profile, contract_tool(admission))],
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
                            matched=matches(proposal, case),
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
        "suite": suite,
        "sampling": sampling,
        "results": rows,
    }


async def exercise(key, selected_profile="both", suite="basic", sampling="diagnostic"):
    async with asyncio.timeout(300):
        return await _exercise(key, selected_profile, suite, sampling)


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        print(
            json.dumps(
                asyncio.run(
                    exercise(
                        request["key"],
                        request.get("admission_profile", "both"),
                        request.get("admission_suite", "basic"),
                        request.get("admission_sampling", "diagnostic"),
                    )
                ),
                ensure_ascii=False,
            )
        )
    except Exception as error:
        print(json.dumps({"failure": "admission_probe_failed", "category": type(error).__name__}))
        raise SystemExit(1) from None
