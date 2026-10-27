"""Независимый oracle: все шесть файлов, актуальная версия и итоговый раунд16."""

import ast

QUESTION = (
    "Создай part_1.py, part_2.py, part_3.py, part_4.py и part_5.py с переменной PART, "
    "соответственно равной 1, 2, 3, 4 и 5. Создай hello_world.py: импортируй все пять "
    "модулей, проверь через assert сумму PART=15, выведи ровно hello world и перевод строки. "
    "Прочитай каждый сохранённый файл. Выполни проверку запуска, затем ещё раз прочитай "
    "главный скрипт и передай краткий итог. Не устанавливай зависимости."
)
CRITERIA = {"script", "verify_project", *(f"part_{index}" for index in range(1, 6))}
TOOLS = [
    "ide_list_files",
    *[tool for _ in range(6) for tool in ("ide_write_file", "ide_read_file")],
    "ide_run_command",
    "ide_read_file",
    "ide_finish_task",
]


async def verify_sources(runtime, scope, binding, main):
    tree = ast.parse(main)
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert names == {f"part_{index}" for index in range(1, 6)}
    assert any(isinstance(node, ast.Assert) for node in tree.body)
    for index in range(1, 6):
        actual = await runtime.client.read(
            scope.user_id, binding, operation="file", path=f"part_{index}.py"
        )
        assert actual["content"] == f"PART = {index}\n"
