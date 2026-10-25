"""Generate deterministic reports and galleries from the evidence registry."""

import argparse
import json
import os
from pathlib import Path

from checks import checklist
from inventory import load
from paths import ARTIFACTS, ASSESSMENT, REGISTRY, REPORT, ROOT, TODO

STATUS = {"passed": "выполнено", "pending": "не проверено", "blocked": "блокировано"}


def link(target, base=REPORT.parent):
    if target.startswith(("https://", "http://")):
        return f"[источник]({target})"
    relative = Path(os.path.relpath(ROOT / target, base)).as_posix()
    return f"[{Path(target).name}](<{relative}>)"


def render(registry):
    """Return every generated file without touching source records or receipts."""
    rows = registry["candidates"]
    checks = {c["id"]: checklist(c) for c in rows}
    lines = [
        "# Отчёт об испытаниях репозиториев",
        "",
        (
            "Текущий срез испытаний; даты, команды, версии и измерения сохранены в квитанциях. "
            "Установка, программная проверка, функциональное воспроизведение и биологическая достоверность учитываются отдельно."
        ),
        "",
        (
            "[Проверки](TODO.md) · [Визуальные результаты](artifacts/README.md) · "
            "[Порядок работы](docs/WORKFLOW.md) · [Реестр](data/registry.json) · [Профили запуска](data/profiles.json)"
        ),
        "",
        "## Сводка",
        "",
        (
            f"Подключено {len(rows)} репозитория. Разбор результатов зарегистрирован для "
            f"{sum(bool(c.get('launch_review')) for c in rows)}; визуальные материалы опубликованы для "
            f"{sum(bool(c.get('visual_artifacts')) for c in rows)}. Наличие исполняемого профиля не означает завершённого испытания."
        ),
        "",
        (
            "Сохраняются **35/43, G0_REVISE, saturation=false**, 15 неранжированных вариантов. "
            "Архитектура генератора не выбрана. Нейродинамика Drosophila, тело и среда, перенос представлений "
            "и человеческий оператор ECAP — отдельные компоненты. Запуск не подтверждает клиническую эффективность."
        ),
        "",
        "| SIM | Репозиторий | Назначение | Текущий результат |",
        "|---|---|---|---|",
    ]
    for row in rows:
        review = row.get("launch_review", {})
        status = review.get("status", "итоговый разбор не завершён")
        lines.append(
            f"| [{row['id']}](#{row['id'].lower()}) | {row['repository']} | {row['role']} | {status} |"
        )
    lines += [
        "",
        "## Происхождение и общие ограничения",
        "",
        f"- Поколение оснований: `{registry['knowledge_generation']}`; исходный срез: `{registry['discovered_at']}`.",
        "- Переименования сохранены в `repository_aliases` реестра; дубли не подключаются.",
        "- Лицензии кода, данных и право распространения производных проверяются раздельно. Отсутствие LICENSE не означает разрешение на использование.",
        "- Различия materialisation, фильтров, знаков, задержек и нормировки весов меняют модель. Сравнение скорости не подтверждает эквивалентность.",
        "- Исторические прогоны с резервом RAM остаются в квитанциях. Текущая политика: без лимита RAM и резерва; до четырёх CPU-потоков, один вычислительный запуск одновременно. GPU проверяется отдельно.",
    ]
    integrity = registry.get("integrity_review")
    maintenance = sorted({c["cleanup"]["receipt"] for c in rows if c.get("cleanup")})
    if maintenance:
        receipt = load(ROOT / maintenance[-1])
        lines += [
            "- Последняя уборка: "
            + link(maintenance[-1])
            + f"; удалено {receipt['removed_bytes'] / 1024**3:.2f} ГиБ временных файлов по логическому размеру. "
            + "Квитанции, численные экспорты и визуальные материалы сохранены."
        ]
    if integrity:
        lines += [
            "- Проверка защищённых файлов: "
            + link(integrity["receipt"])
            + ". Исторический baseline сохранён, его хеши не подменяются."
        ]
    lines += [
        "",
        '<a id="итоги-запусков-и-варианты-использования"></a>',
        "## Результаты по SIM",
        "",
    ]
    assessments, outputs = [], {}
    gallery = [
        "# Визуальные результаты испытаний",
        "",
        "Материалы сгруппированы по SIM. Отсутствие изображения означает отсутствие опубликованной визуальной проверки, а не отсутствие возможностей проекта.",
        "",
        "[Отчёт](../REPORT.md) · [Порядок публикации](../docs/WORKFLOW.md)",
        "",
        "| SIM | Проект | Визуальные материалы |",
        "|---|---|---|",
    ]
    todo = ["# Проверки SIM", ""]
    for row in rows:
        sid = row["id"]
        review, stages = row.get("launch_review", {}), checks[sid]
        todo += [f"- **[{sid} — {row['repository']}](REPORT.md#{sid.lower()})**"]
        for check in stages:
            suffix = " — блокировано, см. отчёт" if check["status"] == "blocked" else ""
            todo.append(
                f"  - [{'x' if check['status'] == 'passed' else ' '}] {check['label']}{suffix}"
            )
        lines += [
            f'<a id="{sid.lower()}"></a>',
            f"### {sid} — {row['repository']}",
            "",
            f"**Исходники:** [{row['commit']}]({row['upstream_tree']}); связанные ресурсы: "
            + (
                ", ".join(row.get("origins", []) + row.get("source_ids", []))
                or "не указаны"
            )
            + ".",
            "",
            "**Данные и версия:** " + row["data_scope_notes"],
            "",
            "**Лицензии:** "
            + link(row["source_inventory"])
            + "; хеши файлов — в реестре.",
            "",
            "| Проверка | Состояние | Основание |",
            "|---|---|---|",
        ]
        for check in stages:
            evidence = "; ".join(link(p) for p in check["evidence"]) or "—"
            lines.append(
                f"| {check['label']} | {STATUS[check['status']]} | {evidence} |"
            )
        if review:
            lines += [
                "",
                f"**Итог ({review['date']}):** {review['summary']}",
                "",
                "**Область проверки:** " + review["scope"],
                "",
                "**Измеренная пиковая RAM, байт:** `"
                + json.dumps(review["memory"], ensure_ascii=False)
                + "`.",
                "",
            ]
            for key, title in [
                ("resolved_issues", "Существенные исправления"),
                ("strengths", "Преимущества"),
                ("weaknesses", "Ограничения"),
            ]:
                lines += [f"**{title}:**", "", *[f"- {v}" for v in review[key]], ""]
            lines += ["| Продолжение | Оценка |", "|---|---|"]
            for key, label in [
                ("adapt", "Адаптация"),
                ("compose", "Композиция сервисов"),
                ("from_scratch", "Собственная реализация"),
            ]:
                lines.append(f"| {label} | {review['options'][key]} |")
            lines += [
                "",
                "**Предварительное решение:** " + review["recommendation"],
                "",
                "**Квитанции:** "
                + "; ".join(link(p) for p in review["receipts"])
                + ".",
                "",
            ]
        else:
            lines += [
                "",
                "Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.",
                "",
            ]
        lines += [f"[Визуальные материалы {sid}](artifacts/{sid}/README.md).", ""]
        visuals = row.get("visual_artifacts", [])
        gallery.append(
            f"| [{sid}]({sid}/README.md) | {row['repository']} | {len(visuals) if visuals else 'пока нет'} |"
        )
        page = [
            f"# {sid} — {row['repository']}",
            "",
            f"[Результат испытаний](../../REPORT.md#{sid.lower()}) · [Все проекты](../README.md)",
            "",
            f"Исходники: `{row['commit']}`.",
            "",
        ]
        if not visuals:
            page += [
                "Проверенных визуальных результатов пока нет. Скриншоты интерфейса, графики и видео будут добавляться по мере фактических испытаний.",
                "",
            ]
        for visual in visuals:
            name = visual["file"]
            page += [f"## {visual['caption']}", "", visual["scope"], ""]
            if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg"}:
                page += [f"![{visual['caption']}]({name})", ""]
            else:
                page += [f"[Открыть {name}]({name})", ""]
            page += [
                "Первичный файл: " + link(visual["source"], ARTIFACTS / sid) + ".",
                "",
                f"SHA-256: `{visual['sha256']}`.",
                "",
            ]
        outputs[ARTIFACTS / sid / "README.md"] = "\n".join(page)
        outputs[ARTIFACTS / sid / "manifest.json"] = (
            json.dumps(
                {"id": sid, "commit": row["commit"], "artifacts": visuals},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        assessments.append(
            {
                "id": sid,
                "commit": row["commit"],
                "role": row["role"],
                "checks": stages,
                "launch_review": review or None,
                "biological_validation": False,
                "human_ecap_operator": False,
            }
        )
    outputs.update(
        {
            REPORT: "\n".join(lines),
            TODO: "\n".join(todo) + "\n",
            ARTIFACTS / "README.md": "\n".join(gallery) + "\n",
            ASSESSMENT: json.dumps(
                {
                    "generation": registry["knowledge_generation"],
                    "candidates": assessments,
                    "integrity_review": integrity,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        }
    )
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for path, content in render(load(REGISTRY)).items():
        if args.check:
            if not path.is_file() or path.read_bytes() != content.encode("utf-8"):
                stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    if stale:
        raise SystemExit("Stale generated files: " + ", ".join(stale))
    print(
        "Generated views are current"
        if args.check
        else "Generated TODO, REPORT, assessment and galleries"
    )


if __name__ == "__main__":
    main()
