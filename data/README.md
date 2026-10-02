# Данные исследовательской базы

В корне находятся только четыре файла ядра, этот индекс и манифест.
Идентификаторы источников и MCP URI стабильны; расположение остальных JSON
задаёт единый реестр `service/data_layout.py`.

| Раздел | Актуальные файлы |
| --- | --- |
| Ядро | [records](records.json), [aliases](aliases.json), [clusters](clusters.json), [ST](ST.json) |
| Схема и словари | [Карточка](schema/source-record.schema.json), [vocabularies](schema/vocabularies.json) |
| Тема и научные границы | [Концепция](research/dissertation-concept.json), [контракт](research/scientific-contract.json), [новизна](research/novelty-landscape.json) |
| Доказательства | [Матрица](evidence/evidence-matrix.json), [человеческие наборы](evidence/human-dataset-matrix.json), [27 адресных проверок](evidence/evidence-review-ledger.json) |
| Сводные проверки | [Аудит](audits/summary/audit-report.json), [полнота полей](audits/summary/completeness-report.json), [применённые проверки](audits/summary/validation-log.json) |
| Поиск и версии | [Протокол](audits/search/search-protocol.json), [SRC-07 coverage](audits/search/src07-coverage-ledger-2026-09-25.json), [SRC-07 версии](audits/search/src07-version-recheck-audit.json), [российский prior art](audits/search/ns15-russian-prior-art-audit.json) |
| Drosophila | [Коннектом](audits/drosophila/drosophila-connectome-audit.json), [ноцицепция](audits/drosophila/drosophila-nociception-audit.json), [NS-04](audits/drosophila/ns04-perturbation-model-audit.json), [PA-01 citations](audits/drosophila/pa01-s775-s782-citation-pass-2026-09-25.json), [runtime](audits/drosophila/runtime-audit.json) |
| Перенос и синтетика | [Synthetic domain](audits/transfer/synthetic-domain-audit.json), [NS-06](audits/transfer/ns06-prior-art-audit.json), [запреты переноса](audits/transfer/forbidden-transfer-audit-2026-09-25.json) |
| ECAP/SCS | [ECAP](audits/ecap-scs/ecap-scs-audit.json), [исходы](audits/ecap-scs/scs-outcome-audit.json), [NS-11 prediction](audits/ecap-scs/ns11-prediction-audit.json), [доступ](audits/ecap-scs/human-ecap-scs-access-audit.json), [trials](audits/ecap-scs/ecap-trial-registry-audit.json), [PA-04 citations](audits/ecap-scs/pa04-citation-audit-2026-09-25.json) |

## Воспроизводимость и хранение

- `curation/`: четыре набора 103 применённых партий с исходными именами,
  payload, SHA-256 и индексами ID — [relevance 3](curation/relevance-3/applied-batches.json),
  [relevance 4](curation/relevance-4/applied-batches.json),
  [relevance 5](curation/relevance-5/applied-batches.json),
  [ST](curation/st-resources/applied-batches.json). Очереди используют относительные
  bundle-локаторы; загрузчик проверяет хеш перед воспроизведением.
  [Реестр запросов](curation/relevance-5/discovery/registry-search.json) и
  [назначение кластеров](curation/cluster-assignments/github-fly-resources-2026-09-23.json)
  сохраняют основания применённых решений.
- `provenance/`: 103 оригинала партий и 15 оригиналов адресных проверок;
  полные payload сверяются с объединёнными наборами и действующими аудитами.
- `archive/`: два базовых миграционных среза и два старых `pre-publish` снимка.
  Оригиналы и снимки, удаление которых ранее отклонила автоматическая проверка,
  сохранены неизменными и не входят в актуальный релиз.
- [Staging](staging/README.md): шаблон и игнорируемая очередь неопубликованных
  кандидатов. Сырые ответы Pi/API, скрипты и логи размещаются в `.work/`.
  Автоматические снимки отката ограничены двумя последними в
  `.work/research-snapshots/`; исторические тестовые входы — `tests/fixtures/history/`.

## Проверка и использование

[Манифест](release-manifest.json) покрывает актуальные JSON, curation, документы,
README, SKILL и TODO; исключает себя, staging, `.work`, archive и provenance.
Агрегат SHA-256 вычисляется по отсортированным строкам `<path>\0<file SHA-256>\n`.
После изменения состава: `uv run --frozen python scripts/check_release.py --write`,
затем `scripts/check.ps1`. Счётчики: `uv run --frozen researchctl stats`.

Научный срез — в [итоговом отчёте](../docs/final-validation-report.md), команды —
в [справочнике](../docs/reference/operations.md), доказательные разборы —
в [документах](../docs/README.md). Датированные проверки сохраняют собственную
область и дату; их исторические открытые состояния не заменяют текущие решения.
Кластеры служат навигацией. Терминальное отсутствие сведений содержит причину,
дату и локатор; недоступность источника не доказывает его отсутствие.
Состояния `not_reported` и `unavailable_after_search` не подменяют факт.
В журнале адресных проверок `#name.json` означает `entries[name.json]`.
Сохранены `G0_REVISE`, `saturation=false`, `STOP-UNSATURATED` и запрет клинических
выводов без связанного набора ECAP/SCS с исходом и разрешением на анализ.
