# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf==2.0", "pillow==13.0.0", "zxing-cpp==3.1.1"]
# ///
"""Validate the printed poster against the locked article and rendered QR codes."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
from pathlib import Path

import pymupdf
import zxingcpp
from PIL import Image

HERE = Path(__file__).resolve().parent
PUBLICATIONS = HERE.parents[2]
ROOT = PUBLICATIONS.parent
ARTICLE = PUBLICATIONS / "documents/PUB-001/neiro-miet/ru"
WORK = ROOT / "research/.work/min2026-poster-20261020"
MM = 72 / 25.4
APPENDIX = "https://github.com/deneal123/AISCS/releases/tag/min-2026-review-v1.0.0"
CONFERENCE = "https://neiromiet.confreg.org"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def validate(output: Path, baseline: Path | None, build_log: Path | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    counts = json.loads((ARTICLE / "review/prisma_counts.json").read_text(encoding="utf-8"))
    metrics = json.loads((ARTICLE / "review/corpus_metrics.json").read_text(encoding="utf-8"))
    assert (
        counts["records_identified_databases"] + counts["records_identified_other_methods"] == 403
    )
    assert 403 - counts["duplicate_records_removed"] == counts["records_screened"]
    assert counts["records_screened"] - counts["records_excluded_title_abstract"] == counts[
        "reports_sought_for_retrieval"
    ]
    assert counts["reports_sought_for_retrieval"] - counts["reports_not_retrieved"] == counts[
        "reports_assessed_for_eligibility"
    ]
    assert counts["reports_assessed_for_eligibility"] - counts["reports_excluded_full_text"] == 130
    assert sum(metrics[key] for key in (
        "dataset_descriptors", "model_studies", "scs_technical_control_studies",
        "descriptive_validation_studies",
    )) == 130

    source = (HERE / "poster.tex").read_text(encoding="utf-8")
    expected_macros = {
        "NPubMed": counts["records_identified_databases"],
        "NEvidenceMap": counts["records_identified_other_methods"],
        "NDuplicates": counts["duplicate_records_removed"],
        "NScreenExcluded": counts["records_excluded_title_abstract"],
        "NUnavailable": counts["reports_not_retrieved"],
        "NFullExcluded": counts["reports_excluded_full_text"],
        "NDatasets": metrics["dataset_descriptors"],
        "NModels": metrics["model_studies"],
        "NTechnical": metrics["scs_technical_control_studies"],
        "NDescriptive": metrics["descriptive_validation_studies"],
        "NCrossSubject": metrics["person_level_validation_yes"],
        "NExternal": metrics["external_validation_yes"],
        "NCalibration": metrics["calibration_yes"],
        "NUncertainty": metrics["uncertainty_yes"],
        "NClinical": metrics["clinical_sample_yes"],
        "NReported": metrics["n_reported_exact"],
        "MedianN": int(metrics["n_median"]),
    }
    # Sample sizes are taken from the published article's actual table.
    article_tree = ast.parse((ARTICLE / "build_article.py").read_text(encoding="utf-8"))
    dataset_function = next(
        node for node in article_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "dataset_table"
    )
    dataset_rows = next(
        ast.literal_eval(node.value) for node in dataset_function.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "rows" for target in node.targets)
    )
    dataset_sizes = {}
    dataset_originals = {}
    for name, macro in (
        ("BioVid", "NBioVid"), ("X-ITE", "NXITE"), ("PhysioPain", "NPhysioPain"),
        ("UNBC", "NUNBC"), ("EmoPain", "NEmoPain"),
    ):
        row = next(row for row in dataset_rows if row[0].startswith(name + ","))
        size = int(re.search(r",\s*(\d+)", row[0])[1])
        expected_macros[macro] = size
        dataset_sizes[name] = size
        dataset_originals[name] = row
    for name, expected in expected_macros.items():
        match = re.search(r"\\def\\" + name + r"\{(\d+)\}", source)
        assert match and int(match[1]) == expected, f"Source data mismatch: {name}"
    assert sha256(HERE / "assets/conference-background.pdf") == sha256(
        ARTICLE / "poster/MIN_2026_poster_A1.pdf"
    )
    fonts = HERE / "assets/fonts"
    provenance = json.loads((fonts / "provenance.json").read_text(encoding="utf-8"))
    for name, item in provenance["files"].items():
        assert sha256(fonts / name) == item["sha256"], f"Font source changed: {name}"
    pdf_path = HERE / "poster_A1_refined.pdf"
    with pymupdf.open(pdf_path) as doc:
        assert len(doc) == 1, "Expected one page"
        page = doc[0]
        dimensions = [page.rect.width / MM, page.rect.height / MM]
        assert abs(dimensions[0] - 594) < 0.02 and abs(dimensions[1] - 841) < 0.02
        text = page.get_text()
        normalized = normalize(text)
        manuscript = (ARTICLE / "manuscript.md").read_text(encoding="utf-8")
        title = next(line[2:] for line in manuscript.splitlines() if line.startswith("# "))
        assert normalize(title) in normalized, "The full article title must be preserved"
        assert "Д. Ф. Вольхин, Д. И. Рябкин, А. Ю. Герасименко" in text
        assert re.search(r"Постер\s*№\s*23\b", text)
        for phrase in (
            "Данные и оцениваемые показатели", "Валидация моделей", "Отбор публикаций",
            "Табл. 1. Примеры наборов данных",
            "Рис. 1. Валидация моделей в корпусе обзора",
            "Самоотчёт", "стимула", "поведение", "FACS/PSPI",
            "BioVid", "X-ITE", "PhysioPain", "UNBC", "EmoPain",
            "21 дубликата", "исключены 185", "Полные тексты 65 работ недоступны",
            "оценены 132, исключены 2, включены 130", "описаний наборов",
            "исследований моделей", "работ SCS", "описательные валидации",
            "Категории пересекаются", "Неописанные процедуры не считались подтверждёнными",
            "Серые ячейки — отсутствие подтверждения", "порядок условный",
            "Одна ячейка — исследование; цветом отмечено подтверждение",
            "Участников разделяют до предобработки", "Скрининг выполнен одним исследователем",
            "Неоднородность задач не позволила провести общий метаанализ точности",
            "Выводы относятся к включённым исследованиям",
            "вызванный составной потенциал действия",
            "ECAP не является прямой мерой интенсивности боли",
            "В авторской схеме решения принимает специалист",
            "модель не изменяет параметры SCS автономно",
            "Оцениваемые показатели зависят от разметки данных",
            "Применимость модели в новых условиях",
            "требует независимой внешней валидации",
        ):
            assert normalize(phrase) in normalized, f"Missing content: {phrase}"
        for phrase in (
            "Выявлены 403 записи", "выполнен скрининг 382 записей",
            "Запрошены 197 полных текстов", "оценены 132", "включены 130",
            "65 текстов недоступны",
        ):
            assert normalize(phrase) in normalized, f"Missing flow count: {phrase}"
        analytical_basis = []
        for section, original, poster_phrase in (
            ("Проверка моделей",
             "Методы сопоставимы только при одинаковых наборе данных, целевой переменной, "
             "способе разбиения и порядке предварительной обработки.",
             "Сопоставление моделей требует согласования исходных данных, целевых переменных, "
             "способов разбиения выборок и порядка предварительной обработки"),
            ("Наборы данных и модальности",
             "количество изображений не заменяет число независимых участников",
             "Кадры и окна одного участника — повторные наблюдения"),
            ("Проверка моделей", "Зависимость наблюдений может завышать точность.",
             "Зависимость наблюдений. Попадание наблюдений одного участника "
             "в обучающую и тестовую выборки создаёт риск завышения точности"),
            ("Наборы данных и модальности",
             "прирост точности может быть связан с попаданием сведений о личности "
             "или условиях регистрации в разные выборки",
             "Попадание наблюдений одного участника в обучающую и тестовую выборки "
             "создаёт риск завышения точности"),
            ("Проверка моделей",
             "предварительную обработку выполнять только по обучающим данным",
             "Участников разделяют до предобработки; "
             "её параметры определяют по обучающим данным"),
            ("Обсуждение",
             "Независимый набор данных позволяет оценить влияние другого протокола "
             "и оборудования, но не заменяет клиническую выборку.",
             "Независимые выборки позволяют оценить влияние различий протоколов "
             "и оборудования. Клиническую применимость оценивают в целевой популяции"),
            ("Проверка моделей",
             "При клиническом применении дополнительно требуются проверка калибровки, "
             "интервал возможных значений и правило отказа при плохом качестве сигнала.",
             "следует воздержаться от числовой оценки"),
            ("Связь с нейростимуляцией спинного мозга",
             "ECAP отражает вызванное стимулом вовлечение нервных волокон "
             "и позволяет контролировать доставленную стимуляцию",
             "Вызванный составной потенциал действия характеризует вызванную активацию "
             "нервных волокон [2]"),
            ("Связь с нейростимуляцией спинного мозга",
             "До проспективной проверки безопасности результат ML-модели "
             "не должен автономно изменять параметры SCS.",
             "В авторской схеме решения принимает специалист; "
             "модель не изменяет параметры SCS автономно"),
        ):
            heading = re.search(r"^#{1,2} " + re.escape(section) + r"$", manuscript, re.M)
            assert heading, f"Missing source section: {section}"
            following = re.search(r"^#{1,2} ", manuscript[heading.end():], re.M)
            end = heading.end() + following.start() if following else len(manuscript)
            assert normalize(original) in normalize(manuscript[heading.end():end])
            assert normalize(poster_phrase) in normalized, f"Missing analysis: {poster_phrase}"
            analytical_basis.append({
                "source": "documents/PUB-001/neiro-miet/ru/manuscript.md",
                "section": section,
                "section_line": manuscript.count("\n", 0, heading.start()) + 1,
                "original_context": original,
                "poster_interpretation": poster_phrase,
            })
        measurements = {}
        for key in (
            "person_level_validation", "external_validation", "calibration", "uncertainty",
            "clinical_sample",
        ):
            value = metrics[f"{key}_yes"]
            denominator = metrics[f"{key}_denominator"]
            percentage = f"{100 * value / denominator:.1f}".replace(".", ",")
            assert re.search(rf"\b{value}/{denominator}\s*[^\d\s]+\s*{percentage}\s*%", text)
            measurements[key] = {"count": value, "denominator": denominator, "percent": percentage}

        with (ARTICLE / "review/article_bibliography.csv").open(
            encoding="utf-8-sig", newline=""
        ) as f:
            bibliography = {int(row["ref_no"]): row for row in csv.DictReader(f)}
        cited = [bibliography[number]["doi"] for number in (1, 35, 2)]
        assert len(re.findall(r"\[\d\] [A-Z][a-z]+", text)) == 3
        links = [link.get("uri") for link in page.get_links() if link.get("uri")]
        for doi in cited:
            assert doi in text and f"https://doi.org/{doi}" in links
        assert APPENDIX in links and "mailto:deneal123@mail.ru" in links
        assert APPENDIX.removeprefix("https://") in text

        font_report = []
        for xref, extension, _fonttype, name, *_ in page.get_fonts():
            font_bytes = doc.extract_font(xref)[3]
            assert extension in {"cff", "otf", "cid"} and "NimbusSans" in name and font_bytes
            font_report.append({"name": name, "embedded": True})
        sizes = set()
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    # TeX uses 72.27 pt/in; PDF uses 72 bp/in.
                    tex_points = round(span["size"] * 72.27 / 72, 1)
                    sizes.add(tex_points)
                    assert tex_points >= 18, f"Unexpected small text: {span['text']}"
                    box = pymupdf.Rect(span["bbox"])
                    assert page.rect.contains(box), f"Off-page text: {span['text']}"
        assert {18.0, 24.0, 30.0, 46.0, 58.0, 80.0}.issubset(sizes)
        takeaway = page.get_text("dict", clip=pymupdf.Rect(145*MM, 234*MM, 572*MM, 274*MM))
        takeaway_spans = [s for b in takeaway["blocks"]
                          for line in b.get("lines", []) for s in line["spans"]]
        assert takeaway_spans and all(
            abs(s["size"] * 72.27 / 72 - 46) < 0.1 for s in takeaway_spans
        ), "The expanded takeaway must use 46 pt type"
        assert max(s["bbox"][3] for s in takeaway_spans) / MM < 270
        # Check actual PDF text, rather than only the declared TeX font sizes.
        typography = {}
        for role, box, minimum_lines in (
            ("takeaway_caption", (22, 264, 190, 286), 2),
            ("takeaway_explanation", (145, 277, 572, 301), 2),
            ("table_caption", (22, 341, 192, 353), 1),
            ("dataset_table", (22, 355, 287, 536), 25),
            ("figure_caption", (307, 450, 572, 462), 1),
            ("figure_legend", (314, 435, 565, 445), 1),
            ("participant_summary", (22, 543, 287, 575), 3),
            ("fair_comparison", (22, 575, 287, 608), 3),
            ("participant_validation", (307, 486, 572, 525), 4),
            ("external_validation", (307, 528, 572, 557), 3),
            ("reliability_explanation", (307, 559, 572, 607), 5),
            ("clinical_sample", (22, 608, 572, 625), 1),
            ("methods", (22, 625, 572, 650), 2),
            ("methods_sources", (22, 650, 572, 665), 1),
            ("scs_explanation", (22, 684, 572, 716), 6),
        ):
            clip = pymupdf.Rect(*(value * MM for value in box))
            lines_checked = 0
            minimum_pt = 22 if role in {
                "dataset_table", "participant_validation", "external_validation",
                "reliability_explanation",
            } else 24
            if role in {"figure_legend", "methods_sources"}:
                minimum_pt = 20
            for block in page.get_text("dict", clip=clip)["blocks"]:
                for line in block.get("lines", []):
                    spans = [span for span in line["spans"] if span["text"].strip()]
                    if not spans:
                        continue
                    assert all(round(s["size"] * 72.27 / 72, 1) >= minimum_pt for s in spans), (
                        f"Text below {minimum_pt} pt in {role}: {spans}"
                    )
                    lines_checked += 1
            assert lines_checked >= minimum_lines, f"Missing text in {role}"
            if role == "methods_sources":
                assert lines_checked == 1, "Search metadata must fit above the SCS panels"
            typography[role] = {"minimum_tex_pt": minimum_pt, "lines_checked": lines_checked}
        interpretations = {}
        comparison_ending = page.search_for(
            "предварительной обработки."
        )
        assert comparison_ending and max(box.y1 for box in comparison_ending)/MM < 606, (
            "The comparison paragraph must not overlap the clinical-sample row"
        )
        for role, box, phrases in (
            ("person_level_validation", (307, 340, 572, 525), (
                "30/98", "Участников разделяют до предобработки",
                "одного участника в обучающую и тестовую выборки",
                "её параметры определяют по обучающим данным",
            )),
            ("external_validation", (307, 340, 572, 558), (
                "11/98", "Независимые выборки позволяют",
                "оценить влияние различий протоколов и оборудования",
                "Клиническую применимость оценивают в целевой популяции",
            )),
            ("probability_and_uncertainty", (307, 340, 572, 607), (
                "0/98", "1/98", "Калибровка и неопределённость",
                "Прогнозируемые вероятности сопоставляют с наблюдаемыми частотами исходов",
                "Неопределённость прогноза оценивают отдельно",
                "При низком качестве сигнала или вне проверенных условий применения "
                "следует воздержаться от числовой оценки",
                "Неописанные процедуры не считались подтверждёнными",
            )),
            ("clinical_sample", (22, 608, 572, 625), (
                "59/98", "Клинический состав выборки не подтверждает независимость валидации",
            )),
            ("participant_sample", (22, 543, 287, 575), (
                "Число уникальных участников установлено для 72 из 130 публикаций",
                "медиана", "66 участников",
                "Кадры и окна одного участника — повторные наблюдения",
            )),
        ):
            clip = pymupdf.Rect(*(value * MM for value in box))
            context = normalize(page.get_text(clip=clip))
            for phrase in phrases:
                assert normalize(phrase) in context, f"Missing adjacent interpretation: {role}"
            interpretations[role] = {"context_mm": box, "phrases_checked": list(phrases)}
        dataset_evidence = {}
        for name, y0, y1, phrases in (
            ("BioVid", 371, 404, (
                "Класс стимула", "Признаки открыты", "данные по запросу",
                "EDA", "ECG", "EMG", "видео",
            )),
            ("X-ITE", 404, 437, (
                "Тепловой / электрический стимул", "По запросу",
                "Видео, аудио", "EDA", "ECG", "EMG",
            )),
            ("PhysioPain", 437, 470, (
                "Самоотчёт; группа", "Открытый доступ", "EDA", "BVP", "температура", "признаки EEG",
            )),
            ("UNBC", 470, 503, (
                "Мимические показатели", "FACS/PSPI", "По запросу; соглашение", "Видео лица",
            )),
            ("EmoPain", 503, 536, ("Защитное поведение", "По запросу", "IMU", "EMG", "видео")),
        ):
            clip = pymupdf.Rect(22 * MM, y0 * MM, 287 * MM, y1 * MM)
            context = normalize(page.get_text(clip=clip))
            assert normalize(name) in context
            assert re.search(rf"\b{dataset_sizes[name]}\b", context)
            for phrase in phrases:
                assert normalize(phrase) in context, f"Wrong dataset description: {name}"
            source_signals = normalize(dataset_originals[name][3])
            for signal in {
                "BioVid": ("EDA", "ECG", "EMG", "видео"),
                "X-ITE": ("видео", "аудио", "EDA", "ECG", "EMG"),
                "PhysioPain": ("EDA", "BVP", "температура", "EEG"),
                "UNBC": ("видео лица",),
                "EmoPain": ("IMU", "EMG", "видео"),
            }[name]:
                assert normalize(signal) in source_signals and normalize(signal) in context, (
                    f"Signal not supported by the published table: {name}: {signal}"
                )
            dataset_evidence[name] = {
                "participants": dataset_sizes[name], "context_mm": list(clip / MM),
                "article_table_signals": dataset_originals[name][3],
                "article_table_access": dataset_originals[name][4],
            }
        # Verify actual PDF paths and cell padding, including wrapped text.
        drawings = page.get_drawings()
        def has_rectangle(box: tuple) -> bool:
            wanted = pymupdf.Rect(*(v * MM for v in box))
            return any(all(abs(a - b) < 0.03 * MM for a, b in zip(
                drawing["rect"], wanted, strict=True
            )) for drawing in drawings)

        assert has_rectangle((22, 355, 287, 536)), "Missing table border"
        assert has_rectangle((307, 340, 572, 447)), "Missing chart frame"
        unit_cells = {}
        for key, label_y, colour in (
            ("person_level_validation", 347, "2549A4"),
            ("external_validation", 369, "4CBD38"),
            ("calibration", 391, "2549A4"),
            ("uncertainty", 413, "2549A4"),
        ):
            band = pymupdf.Rect(313.97*MM, (label_y+11.97)*MM,
                               565.03*MM, (label_y+19.53)*MM)
            cells = sorted(
                [d for d in drawings if d["fill"] and band.contains(d["rect"])],
                key=lambda d: (round(d["rect"].y0/MM, 1), d["rect"].x0),
            )
            assert len(cells) == metrics["model_studies"], f"Wrong cell count: {key}"
            positive_rgb = tuple(int(colour[i:i+2], 16)/255 for i in (0, 2, 4))
            grey_rgb = tuple(int("D5E0EC"[i:i+2], 16)/255 for i in (0, 2, 4))
            confirmed = metrics[f"{key}_yes"]
            for index, drawing in enumerate(cells):
                row, column = divmod(index, 49)
                expected_rect = pymupdf.Rect(
                    (314+column*251/49)*MM, (label_y+12+row*4.1)*MM,
                    (314+(column+1)*251/49-0.7)*MM, (label_y+15.4+row*4.1)*MM,
                )
                assert all(abs(a-b) < 0.03*MM for a, b in zip(
                    drawing["rect"], expected_rect, strict=True
                )), f"Wrong unit-cell geometry: {key}: {index}"
                expected_colour = positive_rgb if index < confirmed else grey_rgb
                assert all(abs(a-b) < 0.002 for a, b in zip(
                    drawing["fill"], expected_colour, strict=True
                )), f"Wrong unit-cell colour: {key}: {index}"
            unit_cells[key] = {
                "confirmed": confirmed, "without_confirmation": len(cells)-confirmed,
                "total": len(cells), "positions_are_illustrative": True,
            }
        table_rect = pymupdf.Rect(21.97 * MM, 354.97 * MM, 287.03 * MM, 536.03 * MM)
        table_paths = [d for d in drawings if table_rect.contains(d["rect"])]
        assert len(table_paths) == 10, "Expected border and nine inner rules"
        for drawing in table_paths:
            assert drawing["fill"] is None, "Table cells must be white"
            assert drawing["color"] == (0, 0, 0), "Table rules must be black"
            assert abs(drawing["width"] * 72.27 / 72 - 1) < 0.01, "Expected 1 pt rules"
        segments = [item[1:] for d in drawings for item in d["items"] if item[0] == "l"]
        for coordinates in (
            *((x, 355, x, 536) for x in (68, 88, 151, 215)),
            *((22, y, 287, y) for y in (371, 404, 437, 470, 503)),
        ):
            wanted = [v * MM for v in coordinates]
            assert any(all(abs(a-b) < 0.03*MM for a, b in zip(
                [*a, *b], wanted, strict=True
            )) for a, b in segments), f"Missing table rule: {coordinates}"
        words = page.get_text("words")
        cell_count = 0
        for x0, x1 in zip((22, 68, 88, 151, 215), (68, 88, 151, 215, 287), strict=True):
            for y0, y1 in zip(
                (355, 371, 404, 437, 470, 503), (371, 404, 437, 470, 503, 536), strict=True,
            ):
                inner = pymupdf.Rect((x0+3)*MM, (y0+3)*MM, (x1-3)*MM, (y1-3)*MM)
                cell_words = [w for w in words if x0*MM < (w[0]+w[2])/2 < x1*MM
                              and y0*MM < (w[1]+w[3])/2 < y1*MM]
                assert cell_words, f"Empty table cell: {(x0, y0, x1, y1)}"
                assert all(inner.contains(pymupdf.Rect(w[:4])) for w in cell_words), (
                    f"Cell overflow: {(x0, y0, x1, y1)}"
                )
                cell_count += 1
        # Check the reference's regular headings, captions and centred sample sizes.
        for phrase in ("Данные и оцениваемые показатели", "Валидация моделей"):
            boxes = page.search_for(phrase, clip=pymupdf.Rect(22*MM, 306*MM, 572*MM, 322*MM))
            assert len(boxes) == 1
            box = boxes[0]
            centre = 154.5 if box.x0 / MM < 300 else 439.5
            assert abs((box.x0 + box.x1) / (2 * MM) - centre) < 0.2
            spans = [s for b in page.get_text("dict", clip=box)["blocks"]
                     for line in b.get("lines", []) for s in line["spans"]]
            assert spans and all("Bold" not in s["font"] for s in spans)
            assert all(abs(s["size"] * 72.27 / 72 - 30) < 0.1 for s in spans)
        gaps = {}
        for role, phrase, edge in (
            ("table_caption", "Табл. 1. Примеры наборов данных", 355),
            ("figure_caption", "Рис. 1. Валидация моделей в корпусе обзора", 447),
        ):
            boxes = page.search_for(phrase)
            assert len(boxes) == 1
            box = boxes[0]
            gap = edge - box.y1 / MM if role == "table_caption" else box.y0 / MM - edge
            assert abs(gap - 4) < 0.3, f"Wrong caption gap: {role}: {gap}"
            gaps[role] = round(gap, 2)
            spans = [s for b in page.get_text("dict", clip=box)["blocks"]
                     for line in b.get("lines", []) for s in line["spans"]]
            assert spans and all("Bold" not in s["font"] for s in spans)
            assert all(abs(s["size"] * 72.27 / 72 - 24) < 0.1 for s in spans)
        block_gaps = {}
        for role, before, after in (
            ("figure_to_note", (307, 450, 572, 462), (307, 467, 572, 485)),
            ("note_to_explanation", (307, 467, 572, 485), (307, 486, 572, 525)),
            ("participant_to_external", (307, 486, 572, 525), (307, 528, 572, 557)),
            ("external_to_uncertainty", (307, 528, 572, 557), (307, 559, 572, 607)),
            ("scs_to_limitations", (22, 684, 572, 716), (22, 721, 572, 740)),
            ("limitations_to_references", (22, 721, 572, 740), (22, 745, 447, 769)),
        ):
            def text_bounds(box: tuple, label: str = role) -> tuple[float, float]:
                clip = pymupdf.Rect(*(value * MM for value in box))
                lines = [line for b in page.get_text("dict", clip=clip)["blocks"]
                         for line in b.get("lines", [])]
                assert lines, f"Missing text in spacing check: {label}"
                return (
                    min(line["bbox"][1] for line in lines)/MM,
                    max(line["bbox"][3] for line in lines)/MM,
                )

            gap = text_bounds(after)[0] - text_bounds(before)[1]
            compact = role in {
                "note_to_explanation", "participant_to_external", "external_to_uncertainty",
            }
            lower, upper = (4.5, 6.5) if compact else (7.7, 9)
            assert lower < gap < upper, f"Wrong block gap: {role}: {gap}"
            block_gaps[role] = round(gap, 2)
        for y0, y1 in zip(
            (355, 371, 404, 437, 470, 503), (371, 404, 437, 470, 503, 536), strict=True,
        ):
            cell_words = [w for w in words if 68*MM < (w[0]+w[2])/2 < 88*MM
                          and y0*MM < (w[1]+w[3])/2 < y1*MM]
            assert len(cell_words) == 1
            assert abs((cell_words[0][0] + cell_words[0][2]) / (2*MM) - 78) < 0.2
        highlighted_implications = {}
        for role, box in (
            ("technical_ecap", (22, 666, 287, 718)),
            ("clinical_patient", (307, 666, 572, 718)),
        ):
            wanted = pymupdf.Rect(*(v * MM for v in box))
            paths = [d for d in drawings if all(abs(a-b) < 0.03*MM
                     for a, b in zip(d["rect"], wanted, strict=True)) and d["fill"]]
            assert len(paths) == 1 and min(paths[0]["fill"]) > 0.9
            clip = wanted + (3*MM, 3*MM, -3*MM, -3*MM)
            words_in_box = page.get_text("words", clip=wanted)
            assert words_in_box and all(clip.contains(pymupdf.Rect(w[:4])) for w in words_in_box)
            highlighted_implications[role] = {"box_mm": box, "fill_rgb": paths[0]["fill"]}
        # Keep the supplied background's logos; add no raster charts or decoration.
        with pymupdf.open(HERE / "assets/conference-background.pdf") as background:
            original_images = {
                (item[2], item[3], pymupdf.Pixmap(background, item[0]).digest)
                for item in background[0].get_images()
            }
        rendered_images = {
            (item[2], item[3], pymupdf.Pixmap(doc, item[0]).digest)
            for item in page.get_images()
        }
        assert rendered_images == original_images, "The background's raster logos changed"

        qr_report = {}
        raster_hashes = {}
        for dpi in (120, 150):
            pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            codes = zxingcpp.read_barcodes(image)
            found = {code.text for code in codes}
            assert {APPENDIX, CONFERENCE}.issubset(found), f"Unreadable QR codes at {dpi} dpi"
            qr_report[str(dpi)] = sorted(found)
            raster_hashes[str(dpi)] = hashlib.sha256(pixmap.samples).hexdigest()
        crops = {
            "title": (18, 123, 578, 226),
            "takeaway": (18, 228, 578, 302),
            "targets": (18, 302, 291, 607),
            "validation": (302, 302, 578, 607),
            "selection": (18, 606, 578, 679),
            "scs": (18, 662, 578, 720),
            "footer": (18, 718, 579, 785),
        }
        for name, box in crops.items():
            clip = pymupdf.Rect(*(value * MM for value in box))
            pixmap = page.get_pixmap(dpi=150, clip=clip, colorspace=pymupdf.csRGB)
            pixmap.save(output / f"{name}.png")

    protected = None
    if baseline:
        inventory = json.loads(baseline.read_text(encoding="utf-8"))["files"]
        current = {
            path.relative_to(ROOT).as_posix(): sha256(path)
            for path in (PUBLICATIONS / "documents/PUB-001").rglob("*") if path.is_file()
        }
        assert inventory == current, "The original PUB-001 tree or supplied template changed"
        protected = len(inventory)
    log = build_log if build_log is not None else WORK / "refined-build/poster.log"
    if build_log is not None:
        assert log.is_file(), f"Build log not found: {log}"
    if log.exists():
        log_text = log.read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"Overfull \\[hv]box|Missing character:", log_text)
    (output / "poster-extracted.txt").write_text(text, encoding="utf-8")
    report = {
        "ok": True,
        "page_count": 1,
        "page_mm": dimensions,
        "all_displayed_words_including_title_and_references": len(text.split()),
        "tex_font_sizes_pt": sorted(sizes),
        "typography_checks": typography,
        "adjacent_interpretations": interpretations,
        "analytical_basis": analytical_basis,
        "highlighted_implications": highlighted_implications,
        "validation_unit_cells": unit_cells,
        "dataset_evidence": dataset_evidence,
        "object_layout": {
            "table_cells_checked": cell_count, "chart_frame": True,
            "minimum_cell_padding_mm": 3, "table_rule_tex_pt": 1,
            "caption_gaps_mm": gaps, "regular_centred_headings_tex_pt": 30,
            "block_gaps_mm": block_gaps,
            "sample_sizes_centred": True,
        },
        "fonts": font_report,
        "source_macros_checked": expected_macros,
        "bundled_fonts": provenance,
        "measurements": measurements,
        "qr_decoded_from_pdf": qr_report,
        "raster_sha256": raster_hashes,
        "links": links,
        "unchanged_input_files": protected,
        "build_log_checked": str(log) if log.is_file() else None,
        "files": {
            name: sha256(HERE / name)
            for name in ("poster.tex", "poster_A1_refined.pdf", "poster_A1_refined.png")
        },
        "article_sources": {
            path.relative_to(PUBLICATIONS).as_posix(): sha256(path)
            for path in (
                ARTICLE / "article.pdf", ARTICLE / "manuscript.md",
                ARTICLE / "build_article.py",
                ARTICLE / "review/prisma_counts.json", ARTICLE / "review/corpus_metrics.json",
                ARTICLE / "review/article_bibliography.csv",
                ARTICLE / "poster/MIN_2026_poster_A1.pdf",
            )
        },
    }
    (output / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=WORK / "refined-qa")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--build-log", type=Path, help="Check the log from this build")
    args = parser.parse_args()
    report = validate(args.output, args.baseline, args.build_log)
    print(json.dumps({key: report[key] for key in (
        "ok", "page_count", "page_mm", "tex_font_sizes_pt", "unchanged_input_files",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
