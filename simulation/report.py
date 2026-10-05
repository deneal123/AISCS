"""Publish a compact current comparison, never a history of worker answers."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
from inventory import REGISTRY, WORK, load, save

DATA = {
    "SIM-001": "MaleCNS; body-demo does not load the graph",
    "SIM-002": "FlyWire v630/v783 and figshare activity; author preprocessed files required",
    "SIM-003": "Author FlyWire export; supplied motor patterns coexist with neural readouts",
    "SIM-004": "Larval escape behaviour and SCAPE muscle recordings; analysis only",
    "SIM-005": "Teacher/student networks; Zenodo 16618353 figure data",
    "SIM-006": "FlyWire v783 default; separate v630 paper scenario",
    "SIM-007": "MaleCNS; confirmatory inputs have frozen MD5 and graph SHA256",
    "SIM-008": "MaleCNS supplemental exports; thresholds alter neuron/edge counts",
    "SIM-009": "166700 neurons; 25088107 edges; external export commit 03358c075000af5379e405b244dd31f1a0fd1401",
    "SIM-010": "Optic-lobe connectivity and Julia paper data; analysis only",
    "SIM-011": "BANC materialisations v626/v850/v888; must match the selected scenario",
    "SIM-012": "FANC data access and coordinate transforms; reconstruction/preparation",
    "SIM-013": "Author ESN weight matrices and task inputs; Julia 1.11",
    "SIM-014": "FlyWire visual LIF model; explicit author data files required",
    "SIM-015": "FlyWire v783 and plastic LFS weights; legacy FlyGym imports",
    "SIM-016": "4-neuron native fixture versus separate MaleCNS v1.0 Feather/SCX scenario",
    "SIM-017": "FlyWire v630; graph-tool network analyses, not neural dynamics",
    "SIM-018": "Connectome-constrained visual network and figure reproduction data",
    "SIM-019": "Pretrained FlyVis responses and visual scale stimuli; comparator",
    "SIM-020": "FlyGym 2.1.0; body/physics assets, no built-in whole-brain connectome",
    "SIM-021": "FlyGym Gymnasium 1.3.2; separate import namespace and MuJoCo 3.2.7",
    "SIM-022": "FlyWire v630; sparse default (~280MB author estimate), dense alternative (~60GB)",
    "SIM-023": "MaleCNS, compiled engine and ViZDoom; game damage is not biological nociception",
    "SIM-024": "FlyWire v630 default; neuronal activation/silencing, no body/environment",
    "SIM-025": "Benchtop and neural-interface recordings from OSF 9hxwe; not an ECAP forward simulator",
    "SIM-026": "CAVE/cloudvolume FlyWire access tutorials; no simulator",
    "SIM-027": "VNC/JAX model; exact lineage of the four S740 matrices still unresolved",
    "SIM-029": "FlyWire FAFB v783 author binary; reduced legacy tests are a separate scenario",
    "SIM-030": "Sealed larval-connectome result bundle; complete numerical pipeline not public at this pin",
    "SIM-031": "Visual-system DMN and pretrained ensemble; not a whole-body/whole-brain simulator",
    "SIM-032": "C. elegans latent model; different organism, Python3.6/PyTorch1.8 environment",
    "SIM-033": "Selected adult/larval sparse matrices and metadata; data preparation only",
}


def license_label(inventory):
    texts = "\n".join(
        v["text"] for k, v in inventory["licenses"].items() if "/" not in k
    )
    if "MIT License" in texts:
        return "MIT"
    if "Apache License" in texts:
        return "Apache-2.0"
    if "GNU GENERAL PUBLIC LICENSE" in texts:
        return "GPL; variant requires review"
    return "not established"


def main():
    registry = load(REGISTRY)
    rows, assessments = [], []
    for candidate in registry["candidates"]:
        sid = candidate["id"]
        source = load(WORK / sid / "source-inventory.json")
        evaluation = candidate.get("evaluation", {})
        launch_review = candidate.get("launch_review")
        status = evaluation.get("status", "not_tested")
        reason = evaluation.get("reason") or next(
            (p.get("reason") for p in evaluation.get("phases", []) if p.get("reason")),
            "",
        )
        if launch_review:
            status = launch_review["status"]
            reason = ""
        assessment = {
            "id": sid,
            "role": candidate["role"],
            "commit": candidate["commit"],
            "license": license_label(source),
            "data_scope": DATA[sid],
            "primary_locator": candidate["upstream_tree"],
            "runtime_status": status,
            "reason": reason,
            "phases": evaluation.get("phases", []),
            "functional_evidence": evaluation.get("functional_evidence"),
            "biological_validation": False,
            "human_ecap_operator": False,
            "launch_review": launch_review,
        }
        assessments.append(assessment)
        link = f"[{candidate['repository']}]({candidate['upstream_tree']})"
        rows.append(
            f"| {sid} | {link} | {candidate['role']} | {assessment['license']} | {status}: {reason or 'see run receipt'} |"
        )
    assets = []
    for path in WORK.glob("SIM-*/assets/*.json"):
        if path.name not in {
            "claude-plastic-weights.json",
            "snedea-connectome.json",
            "flybox-manifest.json",
        }:
            continue
        record = load(path)
        assets.append(
            {
                "name": path.stem,
                "url": record["asset"]["url"],
                "status": record["status"],
                "format_validation": record.get("format_validation"),
                "attempts": [
                    {k: v for k, v in attempt.items() if k != "path"}
                    for attempt in record["attempts"]
                ],
            }
        )
    save(
        Path(__file__).with_name("assessment.json"),
        {
            "candidates": assessments,
            "assets": assets,
            "generation": registry["knowledge_generation"],
        },
    )
    static_count = sum(c["static_python"]["parsed"] for c in registry["candidates"])
    pinned_count = sum(bool(c.get("recorded_commit")) for c in registry["candidates"])
    passed_counts = {
        stage: sum(
            any(
                p.get("stage") == stage and p.get("status") == "passed"
                for p in c.get("evaluation", {}).get("phases", [])
            )
            for c in registry["candidates"]
        )
        for stage in ["install", "native_tests", "smoke", "functional"]
    }
    lines = [
        "# Проверка кандидатов для генератора данных",
        "",
        "Срез исходников: 4 октября 2026. Испытания и редакция отчёта: 5 октября 2026.",
        "",
        "## Текущий результат",
        "",
        f"- Подключены {len(rows)} уникальных репозитория; {pinned_count} используют уже зарегистрированный commit. Остальные закреплены по доступному upstream на датированный срез.",
        "- Адреса `NSSIL/ScaleBreak-FlyVis` и `smpuglie/Pugliese_cpg_2025` учтены как переименования. Дубликаты не подключены.",
        f"- Прочитаны зависимости, лицензии и штатные точки входа; синтаксически разобраны {static_count} Python-файлов. Это проверка исходников, а не функциональное воспроизведение.",
        "- Гибридный поиск и граф проверены на `g-56b4c46e48ad7a8b5db92c99`: четыре сохранённых запроса выполнены в режиме `hybrid`, без ошибок; граф ST106 содержит четыре узла и три связи. Индекс не перестраивался.",
        "- Контейнеры базы остановлены после проверки для освобождения памяти. Их тома и поколение сохранены; повторный запуск допускается после проверки ресурса.",
        "- Вычислительные сценарии ограничены запасом RAM. Успешной установки, полного коннектома или биологической валидации из предварительного допуска не следует.",
        f"- Испытания возобновлены по порядку ID. Принятых установок: {passed_counts['install']}; штатных тестовых профилей: {passed_counts['native_tests']}; CLI/smoke: {passed_counts['smoke']}; полностью завершённых функциональных профилей: {passed_counts['functional']}. У 20 кандидатов подготовлены CPU-профили, у 12 записаны необходимые среды или входы.",
        "- SIM-001 Fly Arena: установлены зависимости, `pip check` и семь штатных тестов прошли. Для Linux подготовлены Mesa/EGL, для pytest на Windows-монтировании применён захват `sys`. Body-demo seeds 1/2/3 завершили по 3 секунды (300 строк каждый; 26,2–26,9 секунды wall time). Пустые нейронные поля сохранены как неприменимые к body-demo.",
        "- Повторяемость body-demo seed 1 подтверждена двумя завершёнными попытками: все 300 численных строк совпадают после исключения wall-time. Параметры CLI, Python, MuJoCo и платформа совпадают; отличается каталог экспорта. Основание: `functional_evidence` в реестре и квитанция проверки CSV/JSON в `.work/`.",
        "- В первоначальной партии дополнительный повтор body-demo seed 1 остановлен защитой RAM после 1,62 секунды. Его 162 строки совпали с началом завершённого seed 1. Этот исторический профиль сохраняет `blocked`; итог последующих проверок полного коннектома приведён ниже. Пиковая память прерванной попытки: 746942464 байта; прекращение собственного контейнера подтверждено. Точное минимальное чтение RAM этой попытки не записывалось; для последующих попыток оно добавлено в журнал.",
        "- Проверена реальная остановка собственного контейнера при падении запаса памяти; чужие контейнеры не останавливались.",
        "- Архитектура генератора не выбрана. Научные статусы: **35/43, G0_REVISE, saturation=false**, 15 неранжированных решений.",
        "- Проверки подготовленного инструмента: Ruff без ошибок; pytest — 10 тестов допуска, закрепления commit, ограничения путей, отмены и остановки очереди. Проверка целостности подтвердила 32 чистых checkout, Git-ссылки и сохранность SHA256 281 защищённого файла. JSON, относительные ссылки, LF и `git diff --check` проверены. Эти результаты не относятся к штатным тестам симуляторов.",
        "",
        "## Реестр и результаты",
        "",
        (
            "Точные commits, ресурсы ST, научные карточки и хеши лицензий: [registry.json](registry.json). "
            "Текущие оценки и первичные маршруты данных: [assessment.json](assessment.json). "
            "Команды отдельных сред: [profiles.json](profiles.json)."
        ),
        "",
        "| ID | Репозиторий на проверенном commit | Назначение | Лицензия исходников | Вычислительный результат |",
        "|---|---|---|---|---|",
        *rows,
        "",
        "## Данные и научные границы",
        "",
        "| ID | Проверенная постановка или необходимый вход |",
        "|---|---|",
        *[f"| {sid} | {description} |" for sid, description in DATA.items()],
        "",
        "- Закреплённый GitHub LFS-маршрут `plastic_weights.pt` claude-fly дважды вернул HTTP404. Это блокировка этого маршрута; доступность иных архивов не проверена. Подмены весов нет.",
        "- Бинарный экспорт snedea получен по закреплённому первичному URL: 12443952 байта; SHA256 `fbf8d440ca1207c7573e1acdd2366f9d0beb9b533c1710f21681264f81b1cc49`. Биологическая идентичность исходного материала не доказывается одним хешем экспорта.",
        "- Получен манифест внешнего экспорта FLYBOX. Получение манифеста не означает загрузку всех частей и выполнение полного сценария.",
        "- У полученного snedea-экспорта проверены SHA256, gzip, размеры, конечность весов, диапазоны и сортировка индексов, полнота метаданных. Исходные FlyWire/root-ID не содержатся в этом бинарном формате; для биологического происхождения нужно отдельное отображение. JSON манифеста FLYBOX и его SHA256 проверены без запуска модели.",
        "- В исходнике snedea `reset` не обнуляет счётчик времени. Подготовленная проверка экспортирует это ограничение и завершается с ошибкой при неполном сбросе. Исполнение этой проверки ещё не проводилось.",
        "- FlyGym2.1.0 и Gymnasium1.3.2 имеют разные интерфейсы и зависимости. Старые `from flygym import Fly` не становятся совместимыми от установки переименованного пакета.",
        "- Sparse-ветка snnTorch на закреплённом commit доступна в коде. Оценка 60ГБ относится к dense-варианту и не служит основанием исключить sparse-проверку.",
        "- Разные materialisations, фильтры рёбер, знаки, задержки и нормы весов дают разные модели. Сравнение скорости не доказывает эквивалентность результатов.",
        "- Тело, игровая сцена, сокращённая сеть, полный зарегистрированный граф и подготовка данных учитываются отдельными сценариями. Авторские оценки скорости не представлены как наши измерения.",
        "- Вариант GPL, область лицензии данных и право распространения производных требуют отдельной проверки; отсутствие LICENSE не является разрешением на переиспользование.",
        "",
        "## Условия продолжения",
        "",
        "Образы и зависимости CPU-профилей ещё не приняты по результатам установки: команды используют upstream-требования, а разрешённые зависимости сохраняются в `dependencies.lock.txt` каждого будущего прогона. Команды не означают готовую проверенную среду. Браузерные проверки, численные сравнения и измерение стоимости экспорта также остаются открытыми.",
        "",
        (
            "После освобождения памяти сначала выполнить небольшие CPU-сценарии SOUP и snedea, затем FlyGym и body-demo Fly Arena. "
            "Полные сети, обучение, Julia/R/MATLAB и GPU требуют своих сред и входов. "
            "У каждого прогона сохраняются команда, профиль, commit, причины остановки и хеш лога в `research/.work/simulator-evaluation/<ID>/<run>/`."
        ),
        "",
        (
            "Установка ограничена 30 минутами, smoke — 10, функциональная проверка — 30. "
            "Одновременно допускается один вычислительный сценарий, до четырёх CPU-потоков, до 4ГБ RAM; сохраняются 2ГБ свободной памяти системы. "
            "Текущие профили CPU отключают GPU. GPU-проверки и измерение VRAM остаются невыполненными."
        ),
        "",
        (
            "Технические требования и три условных варианта продолжения: [generator-requirements.md](generator-requirements.md). "
            "Открытые проверки: [TODO.md](TODO.md)."
        ),
        "",
    ]
    lines.extend([
        "## Итоги запусков и варианты использования",
        "",
        "Для каждого испытанного репозитория: проверенный сценарий и статус, доказательства, исправленные проблемы, плюсы, минусы и три варианта использования. Успешный запуск не означает биологическую валидацию; решение об архитектуре принимается после сравнения кандидатов.",
        "",
    ])
    for candidate in registry["candidates"]:
        review = candidate.get("launch_review")
        if not review:
            continue
        lines.extend([
            f"### {candidate['id']} — {candidate['repository']}",
            "",
            review["summary"],
            "",
            "**Проверено:** " + review["scope"],
            "",
            "**Плюсы:** " + "; ".join(review["strengths"]) + ".",
            "",
            "**Минусы и границы:** " + "; ".join(review["weaknesses"]) + ".",
            "",
            "**Исправлено:** " + "; ".join(review["resolved_issues"]) + ".",
            "",
            "**Измеренная пиковая RAM контейнера:** " + str(review["memory"]) + " байт.",
            "",
        ])
        for key, label in [("adapt", "Доработать"), ("compose", "Объединить сервисами"), ("from_scratch", "Разработать с нуля")]:
            lines.append(f"- **{label}:** {review['options'][key]}")
        lines.extend([
            "",
            "**Предварительное решение:** " + review["recommendation"],
            "",
            "**Квитанции:** " + "; ".join("`" + path + "`" for path in review["receipts"]),
            "",
        ])
    Path(__file__).with_name("evaluation-report.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
