# 06. Артефакты и проверки: что доказывает результат

Каждый запуск оставляет на диске набор файлов и манифест с их хешами. Смысл манифеста
не в красоте: он позволяет проверить, что показанный результат — это ровно те байты,
которые посчитаны, и что они посчитаны той конфигурацией, которую запросили.

## 6.1 Что создаёт каждый режим

```mermaid
flowchart TD
  subgraph FAST["Быстрый · поле + LIF"]
    F1["network.npz"]
    F2["network-events.bin"]
    F3["network-control-events.bin"]
    F4["state-response.bin / state-delta.bin"]
    F5["metadata.json + field-proxy-preview.json"]
  end
  subgraph DETAIL["Подробный · фрагмент"]
    D1["запись E1–REF по времени"]
    D2["диагностика по каждой клетке:<br/>порог, тики, макс. мВ"]
    D3["расписание рёбер fragment"]
    D4["coupled-events.bin, coupled-delta.bin<br/>после обратной связи"]
  end
  subgraph FULL["Полный · вся ЦНС"]
    A1["initial-active.jsonl"]
    A2["control.jsonl"]
    A3["activity.jsonl"]
    A4["signals.npz"]
    A5["coupled-source-events.bin"]
    A6["preview.json + manifest.json"]
  end
```

## 6.2 Манифест полного опыта

```mermaid
flowchart TB
  M["manifest.json"] --> A["kind: experimental-full-population-feedback"]
  M --> B["status: converged"]
  M --> C["graph_sha256 и configuration_sha256"]
  M --> D["baseline_schedule_sha256<br/>feedback_schedule_sha256<br/>control_feedback_schedule_sha256"]
  M --> E["cells, iterations, control_iterations<br/>control_policy, control_omitted, control_passes"]
  M --> F["solver_kernels: accelerated_cell_major / generic / batches"]
  M --> G["batch_settings: окно, бюджет, пулы"]
  M --> H["source_geometry_exclusions"]
  M --> I["endpoint_relocation"]
  M --> J["files: имя, байты, sha256 по каждому файлу"]
```

Четыре числа в этом манифесте — самые информативные. `control_omitted` говорит,
замерялась ли контрольная ветвь или объявлена. `solver_kernels` говорит, каким именно
ядром считали (ускоренным или общим). `source_geometry_exclusions` перечисляет клетки,
чьи синапсы вышли за допуск и были исключены явно, а не молча. `endpoint_relocation`
фиксирует, переносился ли электрод на другой участок.

## 6.3 Цепочка проверок внутри прохода

```mermaid
flowchart TD
  A["манифест геометрии"] --> A1{"graph_sha256<br/>совпал?"}
  A1 -->|нет| X1["Geometry cache belongs to another graph"]
  A1 -->|да| A2{"source_index_sha256<br/>совпал?"}
  A2 -->|нет| X2["Geometry cache source index mismatch"]
  A2 -->|да| A3{"producer_sha256<br/>совместим?"}
  A3 -->|нет| X3["Geometry cache producer is not compatible"]
  A3 -->|да| B["чанк геометрии"]
  B --> B1{"sha256 чанка<br/>совпал?"}
  B1 -->|нет| X4["Packed geometry chunk is truncated / damaged"]
  B1 -->|да| B2{"идентичность клетки<br/>совпала с аудитом?"}
  B2 -->|нет| X5["Packed geometry source identity mismatch"]
  B2 -->|да| C["расчёт батча"]
  C --> D{"все напряжения<br/>конечны?"}
  D -->|нет| X6["Non-finite final GPU voltage"]
  D -->|да| E["архив: каждая клетка<br/>получила ровно одну запись"]
  E --> E1{"архив полон<br/>по активным источникам?"}
  E1 -->|нет| X7["Incomplete active source population<br/>event_archive.py:205"]
  E1 -->|да| F{"хеш архива<br/>совпал с квитанцией?"}
  F -->|нет| X8["Event archive changed or digest mismatch<br/>(в кеше: Carried / Cached<br/>population archive digest mismatch)"]
  F -->|да| G["публикация"]
```

Каждый отказ здесь — не аварийная ситуация, а штатный результат: система
предпочитает не опубликовать, чем опубликовать неизвестно что.

## 6.4 Формат архива событий

```mermaid
flowchart LR
  A["EventArchive<br/>одна строка JSONL на клетку"] --> B["ключ — body id"]
  B --> C["edge_events: события рёбер"]
  C --> D["candidates: кандидаты синапсов"]
  D --> E["omitted_empty_candidates: клетка молчала"]
```

Порядок строк детерминирован: это позволяет сравнивать архивы побайтово. Именно так
проверялась эквивалентность: архивы прогонов с разными кешами и с паузой совпали с
базовым прогоном побайтово — `initial-active.jsonl`
`60cee23e…`, `control.jsonl` `7c4ae747…`, `signals.npz` `95376b52…`.

## 6.5 Квитанция прогресса

```mermaid
sequenceDiagram
  participant W as Процесс расчёта
  participant P as progress.json
  participant B as Backend
  participant F as Фронтенд
  W->>P: атомарная запись (временный файл + rename)
  B->>P: чтение
  B->>F: WebSocket: phase, done, total, iteration
  F->>F: проверка фазы и границ<br/>(validFieldProgress / validFullProgress)
  F->>F: отрисовка прогресса или отказа
```

Атомарность записи через rename — не формальность: без неё backend иногда читал
половину JSON и показывал оператору скачок прогресса назад. Фронтенд дополнительно
проверяет, что `done ≤ total`, `total` не больше числа клеток, а номер итерации в
пределах 1..100: некорректный прогресс не рисуется вообще.

## 6.6 Как проверить результат самостоятельно

```mermaid
flowchart TD
  A["два прогона с разными настройками<br/>или с паузой"] --> B["сравнить manifest.json:<br/>configuration_sha256"]
  B --> C{"совпали?"}
  C -->|да| D["сравнить files[].sha256 попарно"]
  D --> E{"все совпали?"}
  E -->|да| F["прогоны эквивалентны побайтово"]
  E -->|нет| G["различие: искать в manifest.json,<br/>чем прогоны отличались"]
  C -->|нет| H["разные конфигурации: результат<br/>сравнивать нельзя, только читать"]
```

Отдельного скрипта сверки в репозитории нет: сверка — это несколько строк на
`hashlib.sha256` по каждому файлу из `files[]`. В рабочем каталоге измерений лежит
`R:/Aspa/.work/connectome-routing-20261028/compare-archives.py`, которым проверялись
кеши и пауза. Правило, которое он проверяет, важнее самого скрипта: любой кеш обязан
давать побайтово тот же архив, иначе он выключается.
