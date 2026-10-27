"""Acceptance model decisions; execution and evidence stay in product services."""

import hashlib

SCRIPT = "print('hello world')\n"
BROKEN_SCRIPT = "print('wrong output')\n"
STOP_SCRIPT = (
    "import pathlib, subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', 'import os,time; os.setsid(); time.sleep(90)'])\n"
    "pathlib.Path('started.txt').write_text('ready')\n"
    "time.sleep(90)\n"
)


def steps(scenario):
    if scenario == "long":
        from scripts.harness_live.long_run import steps as long_steps

        return long_steps()
    if scenario not in {"hello", "repair", "stop"}:
        raise ValueError("acceptance_unknown_scenario")
    read = ("ide_read_file", {"path": "hello_world.py"})
    check = (
        "ide_run_command",
        {
            "profile": "python_script",
            "target": "hello_world.py",
            "command": None,
            "expected_stdout": "hello world\n",
            "timeout_sec": 60 if scenario == "stop" else 10,
            "criterion_id": "verify_project",
        },
    )
    result = [
        ("ide_list_files", {"path": ""}),
        (
            "ide_write_file",
            {
                "path": "hello_world.py",
                "content": BROKEN_SCRIPT
                if scenario == "repair"
                else STOP_SCRIPT
                if scenario == "stop"
                else SCRIPT,
                "base_digest": "",
            },
        ),
        read,
        check,
    ]
    if scenario == "repair":
        result.extend(
            [
                read,
                (
                    "ide_edit_file",
                    {
                        "path": "hello_world.py",
                        "old": BROKEN_SCRIPT,
                        "new": SCRIPT,
                        "base_digest": hashlib.sha256(BROKEN_SCRIPT.encode()).hexdigest(),
                    },
                ),
                read,
                (
                    check[0],
                    {
                        key: value
                        for key, value in {**check[1], "timeout_sec": 11}.items()
                        if key != "command"
                    },
                ),
            ]
        )
    result.append(
        (
            "ide_finish_task",
            {"summary": "Скрипт создан и проверен запуском.", "outcome": "changed"},
        )
    )
    return result


def next_step(scenario, completed):
    plan = steps(scenario)
    expected = [name for name, _args in plan]
    if completed != expected[: len(completed)] or len(completed) > len(plan):
        raise ValueError("acceptance_unexpected_tool_history")
    return plan[len(completed)] if len(completed) < len(plan) else None
