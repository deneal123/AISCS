"""Шестнадцать настоящих продуктовых раундов, без подмены файлов или проверки."""


def files():
    parts = {f"part_{index}.py": f"PART = {index}\n" for index in range(1, 6)}
    main = "".join(f"import part_{index}\n" for index in range(1, 6))
    main += "assert " + " + ".join(f"part_{index}.PART" for index in range(1, 6)) + " == 15\n"
    main += "print('hello world')\n"
    return {**parts, "hello_world.py": main}


def criteria():
    return [
        {
            "criterion_id": "script" if path == "hello_world.py" else path.removesuffix(".py"),
            "kind": "file",
            "target": path,
        }
        for path in files()
    ]


def steps():
    plan = [("ide_list_files", {"path": ""})]
    for path, content in files().items():
        plan.extend(
            [
                ("ide_write_file", {"path": path, "content": content, "base_digest": ""}),
                ("ide_read_file", {"path": path}),
            ]
        )
    plan.extend(
        [
            (
                "ide_run_command",
                {
                    "profile": "python_script",
                    "target": "hello_world.py",
                    "command": None,
                    "expected_stdout": "hello world\n",
                    "timeout_sec": 10,
                    "criterion_id": "verify_project",
                },
            ),
            ("ide_read_file", {"path": "hello_world.py"}),
            (
                "ide_finish_task",
                {
                    "summary": "Шесть файлов сохранены; модули подключены, запуск проверен.",
                    "outcome": "changed",
                },
            ),
        ]
    )
    return plan
