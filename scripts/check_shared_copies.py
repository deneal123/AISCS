"""Побайтовая сверка намеренно раздвоенных файлов backend ↔ agents.

⚠️ ЗАЧЕМ РАЗДВОЕНЫ. Это не контракт между сервисами, а по копии одного и того же у каждой
стороны: клиент ТРЕТЬЕЙ стороны (каталог openrouter.ai) и векторы, против которых каждая
сторона гоняет СВОЮ реализацию. Общий пакет ради нескольких сотен строк stdlib связал бы
релизы двух сервисов; поход backend за каталогом через сайдкар превратил бы независимое
чтение в жёсткую зависимость.

⚠️ ЗАЧЕМ ГЕЙТ. Расхождение таких копий не падает — оно тихо меняет поведение одной
стороны: `TOOL_CAPABLE_*` решают, кому давать инструменты, `STATIC_CONTEXT_WINDOWS` —
сколько контекста влезет, а отставшая копия `net_guard` пропустит внутренний адрес.

🔴 ГЛАВНОЕ. Копия каталога уже разошлась на полгода: в сайдкар добавили прокси через
`providers._http` — модуль, которого у backend нет, — и сверка стала НЕИСПОЛНИМОЙ.
Гейт при этом молчал, потому что жил только в CI, а CI на этом репозитории красный на
уровне заданий. Отсюда два вывода, зашитые сюда:

1. Файл в списке обязан быть самодостаточным: только stdlib и то, что есть у ОБЕИХ
   сторон. Импорт своего = гейт больше не выполним в принципе.
2. Проверка живёт в pre-commit суперпроекта, а не только в CI: гейт, который негде
   выполнить, — это не гейт.

Зависимостей нет — только stdlib.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (что это, путь backend, путь agents)
PAIRS: list[tuple[str, str, str]] = [
    (
        "единая политика класса и бесплатной локальной модели",
        "backend/service/shared/model_class.py",
        "agents/service/shared/model_class.py",
    ),
    (
        "immutable document review identity",
        "backend/service/shared/document_review.py",
        "agents/service/shared/document_review.py",
    ),
    (
        "immutable document review identity (workspace)",
        "agents/service/shared/document_review.py",
        "workspace/service/domain/documents/document_review.py",
    ),
    (
        "versioned semantic block patch",
        "backend/service/shared/block_patch.py",
        "agents/service/shared/block_patch.py",
    ),
    (
        "versioned semantic block patch (workspace)",
        "agents/service/shared/block_patch.py",
        "workspace/service/domain/documents/block_patch.py",
    ),
    (
        "private bounded instruction refinement",
        "backend/service/shared/harness_refinement.py",
        "agents/service/shared/harness_refinement.py",
    ),
    (
        "private acknowledged harness protocol",
        "backend/service/shared/harness_protocol.py",
        "agents/service/shared/harness_protocol.py",
    ),
    (
        "private task contract and completion codec",
        "backend/service/shared/task_contract.py",
        "agents/service/shared/task_contract.py",
    ),
    (
        "human question and private continuation codec",
        "backend/service/services/chat/domain/human_questions/contracts.py",
        "agents/service/shared/human_question.py",
    ),
    (
        "AgentEvent transport contract",
        "backend/service/infrastructure/agents_client/contracts/events.py",
        "agents/service/events.py",
    ),
    (
        "protocol manifest loader",
        "backend/service/infrastructure/agents_client/contracts/protocol_manifest.py",
        "agents/service/protocol_manifest.py",
    ),
    (
        "каталог моделей",
        "backend/service/services/chat/infrastructure/model_catalog.py",
        "agents/service/shared/model_catalog.py",
    ),
    *(
        (
            f"векторы {name}",
            f"backend/tests/vectors/{name}.json",
            f"agents/tests/vectors/{name}.json",
        )
        for name in (
            "net_guard_vectors",
            "token_estimate_vectors",
            "model_class_vectors",
        )
    ),
    # ⚠️ ТРЕТЬЯ сторона у SSRF-векторов: сайдкар песочницы качает файлы пользователя по
    # презайнед-ссылке, то есть ходит в сеть по адресу, который пришёл снаружи. Своя
    # реализация, общие векторы — тот же приём, что у первых двух. Сверяем с `agents`:
    # достаточно любой пары в цепочке, раз первая пара уже сверена с backend.
    (
        "векторы net_guard_vectors (workspace)",
        "agents/tests/vectors/net_guard_vectors.json",
        "workspace/tests/vectors/net_guard_vectors.json",
    ),
]

# Импорты, которых в раздвоенном ФАЙЛЕ КОДА быть не может: они есть только у одной
# стороны, а значит делают побайтовую сверку невыполнимой (см. докстринг).
_FORBIDDEN_IMPORTS = (
    "service.domain",
    "service.application",
    "service.services",
    "service.composition",
)


def main() -> int:
    problems: list[str] = []
    for what, left, right in PAIRS:
        lpath, rpath = ROOT / left, ROOT / right
        pair_missing = False
        for p in (lpath, rpath):
            if not p.exists():
                problems.append(f"{what}: нет файла {p.relative_to(ROOT)}")
                pair_missing = True
        if pair_missing:
            continue
        # Читаем БАЙТАМИ, но с нормализацией концов строк: рабочее дерево на Windows
        # может держать CRLF, в гите же оба файла лежат с LF (`.gitattributes`).
        lraw = lpath.read_bytes().replace(b"\r\n", b"\n")
        rraw = rpath.read_bytes().replace(b"\r\n", b"\n")
        if lraw != rraw:
            problems.append(f"{what}: {left} и {right} РАЗЛИЧАЮТСЯ")
            continue
        if lpath.suffix == ".py":
            text = lraw.decode("utf-8")
            for bad in _FORBIDDEN_IMPORTS:
                if f"import {bad}" in text or f"from {bad}" in text:
                    problems.append(
                        f"{what}: импорт `{bad}` есть только у одной стороны — "
                        f"сверка копий станет невыполнимой"
                    )
        print(f"  ok  {what}")

    if problems:
        print("\nРАСХОЖДЕНИЕ раздвоенных копий:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
