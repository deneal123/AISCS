"""Derive a checklist from evidence; a historical refusal is not a current blocker."""

import json

from paths import ROOT

LABELS = {
    "source": "Проверить закреплённые исходники, зависимости и лицензию",
    "environment": "Установить окружение и проверить зависимости",
    "software": "Выполнить штатные или явно обозначенные программные проверки",
    "smoke": "Проверить минимальный запуск или CLI",
    "functional": "Выполнить функциональный сценарий с согласованными данными",
    "reproducibility": "Проверить повторяемость короткого сценария и seeds, где применимо",
    "visuals": "Сохранить проверенные визуальные материалы",
    "review": "Записать итог, ограничения и три варианта применения",
    "cleanup": "Удалить временные окружения, кэши и ненужные ресурсы запуска",
}


def contains_repeat_proof(value):
    if isinstance(value, dict):
        for key in ("repeat_seed_equal", "repeat_content_equal", "repeat_equal"):
            if value.get(key) is True and value.get("status") not in {
                "failed",
                "blocked",
            }:
                return True
        return any(contains_repeat_proof(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_repeat_proof(v) for v in value)
    return False


def checklist(row):
    evaluation = row.get("evaluation", {})
    review = row.get("launch_review", {})
    phases = {p["stage"]: p for p in evaluation.get("phases", [])}
    receipts = review.get("receipts", [])
    result_path = evaluation.get("result")
    result = []
    for key, label in LABELS.items():
        item = {"id": key, "label": label, "status": "pending", "evidence": []}
        stage = {
            "environment": "install",
            "software": "native_tests",
            "smoke": "smoke",
            "functional": "functional",
        }.get(key)
        if stage:
            phase = phases.get(stage, {})
            if phase.get("status") == "passed":
                item.update(
                    status="passed", evidence=[result_path] if result_path else receipts
                )
            elif (
                phase.get("status") in {"failed", "blocked"}
                and phase.get("reason") != "host_memory_reserve"
            ):
                item.update(
                    status="blocked",
                    evidence=[result_path] if result_path else receipts,
                )
        if (
            key == "source"
            and row.get("checkout_clean")
            and row.get("source_inventory")
        ):
            item.update(
                status="passed",
                evidence=[row["source_inventory"], row["upstream_tree"]],
            )
        if key == "functional" and row["id"] in {"SIM-001", "SIM-003"} and review:
            # These later, explicitly reviewed receipts supersede the earlier generic phase.
            item.update(status="passed", evidence=receipts)
        if key == "functional" and row["id"] == "SIM-002" and review:
            item.update(status="blocked", evidence=receipts)
        if key == "reproducibility":
            proof_paths = []
            for relative in receipts:
                path = ROOT / relative
                if path.suffix != ".json" or not path.is_file():
                    continue
                try:
                    proof = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if contains_repeat_proof(proof):
                    proof_paths.append(relative)
            legacy = evaluation.get("functional_evidence", {})
            if legacy.get("repeat_seed_status") == "verified_across_completed_attempts":
                proof_paths.append(legacy["receipt"])
            if proof_paths:
                item.update(status="passed", evidence=sorted(set(proof_paths)))
        if key == "visuals" and row.get("visual_artifacts"):
            item.update(
                status="passed", evidence=[x["source"] for x in row["visual_artifacts"]]
            )
        if key == "review" and review and receipts:
            item.update(status="passed", evidence=receipts)
        if key == "cleanup" and row.get("cleanup", {}).get("status") == "completed":
            item.update(status="passed", evidence=[row["cleanup"]["receipt"]])
        override = row.get("check_overrides", {}).get(key)
        if override:
            item.update(override)
        result.append(item)
    return result
