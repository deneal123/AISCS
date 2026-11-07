"""Create a shareable text inventory without copying third-party data or local logs."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
items = json.loads((HERE / "simulator-inventory.json").read_text(encoding="utf-8"))["candidates"]
manifest = json.loads((HERE / "simulator-receipts-manifest.json").read_text(encoding="utf-8"))
assert len(items) == manifest["candidate_count"] == 32

# Independently read from the pinned checkout and matched to source-inventory.json.
# This concerns the repository-level file only; bundled assets may differ.
VERIFIED_LICENSE_FILES = {
    "SIM-007": (
        "MIT",
        "LICENSE",
        "a2e604e6c25635d6eb9d0fea6e1bd068875a87a401c8265fb506c3b5a31f3481",
    ),
    "SIM-010": (
        "MIT",
        "LICENSE",
        "58aeab0bfecc96ce5e8ce09286cbaaf75d18d43959dbfb32fa8a12af952e0e67",
    ),
    "SIM-012": (
        "GPL version 3",
        "LICENSE",
        "230184f60bae2feaf244f10a8bac053c8ff33a183bcc365b4d8b876d2b7f4809",
    ),
    "SIM-018": (
        "MIT",
        "LICENSE",
        "5ca2920d4f56954100c8f365461aba7b6c6154da49734f7b2703d9275ad49d11",
    ),
    "SIM-021": (
        "Apache License 2.0",
        "LICENSE",
        "1eb85fc97224598dad1852b5d6483bbcf0aa8608790dcc657a5a2a761ae9c8c6",
    ),
    "SIM-025": (
        "MIT",
        "LICENSE",
        "6b0369bb0b593b2b1441842859b721e7fa47f3e0daae1fa59c05984d106df454",
    ),
    "SIM-030": (
        "MIT",
        "LICENSE",
        "4cd8648a2959cfac09cce697b5be797bc0f11baf42aecca9bd57312f9108532e",
    ),
    "SIM-031": (
        "MIT",
        "license",
        "ffdd9afb62e09f906d762ec1ea37ffe80fec7de415964e249e46cf20999d0ab2",
    ),
}

VERIFIED_LICENSE_COMMITS = {
    "SIM-007": "e80dcf643beefff08afd936a741ac8cc50723cb4",
    "SIM-010": "3352e97c37b0f96ab08f27b70b4420f3d4ac2726",
    "SIM-012": "89d9769457583051e3ec9ec7b34a5f3575537bf5",
    "SIM-018": "336e0d12a6edd92a7340cfffb71985a3879055ce",
    "SIM-021": "d285260a1c8a7b3494150cd1590f2c9fe4b5e06b",
    "SIM-025": "604d17fe1d39a6618fd8f26694922a823aeed8c8",
    "SIM-030": "af8e451d9010294c185b966c953616b212f0294c",
    "SIM-031": "92b3845cc426dd309a1a0e1b3890156c42e14021",
}
if VERIFIED_LICENSE_FILES.keys() != VERIFIED_LICENSE_COMMITS.keys():
    raise ValueError("Verified license files and commits differ")
for item in items:
    expected_commit = VERIFIED_LICENSE_COMMITS.get(item["id"])
    if expected_commit is not None and item["commit"] != expected_commit:
        raise ValueError(f"License for {item['id']} must be rechecked for the new commit")


def sentence(text: str) -> str:
    """End registry descriptions once without altering their contents."""
    return text if text.rstrip().endswith((".", "!", "?", "…")) else text + "."


out = [
    "# Дополнительные сведения: исследованные программные ресурсы",
    "",
    "Рабочая версия приложения к обзору программных средств. Сводка относится к указанным "
    "коммитам и ограниченным сценариям; она не подтверждает воспроизведение всех заявленных "
    "авторами функций или биологическую достоверность. Публичный постоянный адрес приложения "
    "ещё не назначен.",
    "",
    "Для каждого проекта сначала перечислены версия, данные и результат, затем ограничения. "
    "`passed` означает положительную отметку конкретного пункта реестра, `blocked` — "
    "открытую блокировку. Проверка повторяемости в отдельных проектах относится к разным "
    "сценариям и не предполагает идентичного протокола. Лицензия указана так, как она "
    "записана в реестре, и должна проверяться отдельно для кода, данных и весов.",
    "",
]
for item in items:
    url = item["url"].removesuffix(".git")
    commit = item["commit"]
    checks = item["checks"]
    out.extend(
        [
            f"## {item['id']} — {item['repository']}",
            "",
            f"- Исходники: {url}/tree/{commit}; commit `{commit}`.",
            sentence(f"- Назначение: {item['role']}; данные и версия: {item['data']}"),
            f"- Лицензия по реестру: {item['license_recorded'] or 'не установлена'}.",
            "- Отметки реестра: "
            + "; ".join(
                f"{label}: {checks.get(key, 'не указано')}"
                for key, label in (
                    ("environment", "окружение"),
                    ("software", "программные проверки"),
                    ("smoke", "минимальный запуск"),
                    ("functional", "функциональный сценарий"),
                    ("reproducibility", "повторяемость"),
                )
            )
            + ".",
            f"- Результат: {item['result']}",
            f"- Условия и ограничения: {item['scope']}",
            "",
        ]
    )
    if item["id"] in VERIFIED_LICENSE_FILES:
        license_name, license_path, license_sha256 = VERIFIED_LICENSE_FILES[item["id"]]
        out.extend(
            [
                f"- Уточнение: в исходниках закреплённого commit файл "
                f"[{license_path}]({url}/blob/{commit}/{license_path}) содержит {license_name} "
                f"(SHA-256 `{license_sha256}`). "
                "Пустое поле реестра не означает отсутствия лицензии; условия данных и "
                "встроенных сторонних материалов проверяются отдельно.",
                "",
            ]
        )
    if item["id"] == "SIM-001":
        if commit != "12f48c702ed170b5bdc4643afa7ce65e952b353d":
            raise ValueError("SIM-001 graph scope must be rechecked for the new commit")
        out.extend(
            [
                "- Уточнение охвата графа: сохранённый manifest описывает отбор клеток с "
                "назначенным superclass при исключении Glia и рёбра между ними. В нём "
                "25 582 938 обозначает рёбра, а 124 177 617 — синаптические контакты; "
                "это не одно и то же. Термин «полный» выше относится к выбранному графу, "
                "а не ко всей периферической нервной системе. SHA-256 исходного локального "
                "manifest: `742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2`.",
                "",
            ]
        )
(HERE / "supplement-inventory.md").write_text("\n".join(out), encoding="utf-8", newline="\n")
print(f"{len(items)} candidates")
