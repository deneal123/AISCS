"""Синтетический PDF: неверный ID → диагностика → одно корректное предложение."""


def block(identity, title, text):
    return {
        "block_id": identity,
        "kind": "slide",
        "title": title,
        "text": text,
        "items": [],
        "columns": [],
        "rows": [],
        "source_id": 0,
        "asset_path": "",
        "level": 1,
    }


def contract():
    return {
        "kind": "document",
        "criteria": [{"criterion_id": "slides", "kind": "pdf", "target": "documents/cats"}],
        "needs_clarification": False,
        "question": "",
    }


def next_step(completed):
    assert all(name == "tex_propose_structure" for name in completed)
    if len(completed) >= 2:
        return None
    return "tex_propose_structure", {
        "base_version": 2,
        "replacements": [
            block(
                "missing" if not completed else "intro", "Мир котиков", "Коты — домашние хищники."
            ),
        ],
        "insertions": [
            {
                "after_id": "intro",
                "block": block("new_care", "Забота", "Вода, корм и игра каждый день."),
            },
        ],
        "deletions": [],
        "moves": [],
    }
