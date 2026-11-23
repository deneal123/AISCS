# 03. Подробный расчёт: фрагмент из клеток с реальными кабелями

Режим «Подробный» решает уравнение кабеля для настоящих клеток — но только для
небольшого фрагмента (до 256 клеток), найденного по координатам контактов. Дальше
события этого фрагмента подаются в сеть ЦНС как вынужденные входы.

## 3.1 Поиск фрагмента по контактам

```mermaid
flowchart TD
  A["Оператор задал E1, REF, STIM+, STIM−"] --> B["contactScreen по четырём контактам"]
  B --> C["spatialCandidates: подбор радиуса<br/>до 8 попыток, 5..200 мкм, 1..256 клеток<br/>растёт ×2, затем делится пополам"]
  C --> D{"нашли допустимый набор?"}
  D -->|нет| E["оператор видит отказ и меняет радиус<br/>или положение контактов"]
  D -->|да| F["createFragmentPopulation<br/>configuration: source_ids, simulation,<br/>allow_partial_geometry = true"]
  F --> G["POST /simulator/fragment-population-runs"]
  G --> H["Celery → POST /v1/fragment-population-executions"]
```

Радиус подбирается автоматически, потому что плотность клеток вдоль разных нервов
разная: у нерва с сотней волокон шаг 5 мкм даёт тысячи кандидатов, у тонкого — ноль.

## 3.2 Что делает генератор: run_fragment_population

```mermaid
flowchart TB
  S["run_fragment_population<br/>R:/Aspa/generator/service/application/population/runner.py:23"] --> P1["Проверка геометрии каждой клетки:<br/>preflight_outgoing_fragment_geometry"]
  P1 --> P2{"все синапсы в пределах max_distance_um?"}
  P2 -->|нет, и allow_partial_geometry = false| X["отказ: Unresolved geometric candidate:<br/>source …, N/M graph synapses outside … um"]
  P2 -->|да или разрешено частично| P3{"solver backend?"}
  P3 -->|experimental_cuda| G1["replay_gpu_batch: активный прогон<br/>и контрольный (current_na = 0.0)"]
  P3 -->|coreneuron / reference| G2["simulate_registered_swc_reference<br/>по одному и тому же SWC"]
  G1 --> D1["registered_outgoing_fragment_diagnostics<br/>для каждой клетки: порог, тики, макс. мВ"]
  G2 --> D1
  D1 --> D2{"участок дальше max_distance_um?"}
  D2 -->|да, при allow_partial_geometry| D3["статус geometry_unresolved,<br/>все значения обнулены в null"]
  D2 -->|нет| D4["fragment_edge_schedule: события → расписание доставок"]
  D3 --> D4
  D4 --> R1["record_independent_cells: запись E1–REF"]
  D4 --> R2["run_fragment_population_network:<br/>LIF-сеть с вынужденными входами"]
```

Здесь важно, что активный и контрольный прогоны отличаются ТОЛЬКО током стимула:
`{**simulation_parameters, 'current_na': 0.0}`. Всё остальное — та же геометрия, тот же
порог, тот же dt. Поэтому разница между ними и есть вклад стимула.

## 3.3 Как события клетки превращаются в расписание сети

```mermaid
flowchart LR
  C1["напряжение сегмента-кандидата<br/>по шагам dt"] --> C2["пересечение порога СНИЗУ ВВЕРХ<br/>(preceding < threshold) и (selected ≥ threshold)"]
  C2 --> C3["tick = ceil(округлённое время)"]
  C3 --> C4["edge_events: источник, цель, знак, вес, задержка"]
  C4 --> C5["LIF-сеть: вынужденные входы<br/>подаются в указанные тики"]
  C5 --> C6["сеть отвечает собственными спайками<br/>и подавляет входами источники"]
```

Пересечение ищется однократно и только снизу вверх: сегмент, который уже был выше
порога, не даёт нового события, пока не вернётся ниже. Это делает события функцией
формы сигнала, а не шага дискретизации.

## 3.4 Обратная связь по фрагменту: iterate_population_feedback

```mermaid
flowchart TB
  A["сеть отработала duration_ms"] --> B["suppressed_source_inputs:<br/>какие входы получили бы источники"]
  B --> C["map_lif_feedback: сопоставление<br/>событий сети с реальными синапсами<br/>по координатам"]
  C --> D["match_fragment_inputs_batch:<br/>проверенные пары синапсов<br/>с обеих сторон"]
  D --> E["population_feedback_schedule:<br/>новое расписание доставок"]
  E --> F{"подпись расписания<br/>совпала с предыдущей?"}
  F -->|"да, unresolved пуст"| G["converged"]
  F -->|"да, но unresolved непуст"| G2["converged_partial"]
  F -->|нет| H{"подпись уже встречалась<br/>раньше (не подряд)?"}
  H -->|да| I["cycle_detected: это цикл,<br/>а не сходимость"]
  H -->|нет| J{"итераций < max_iterations?"}
  J -->|да| A
  J -->|нет| K["iteration_limit"]
  G --> L["публикуется: запись,<br/>сеть, расписание, feedback_alignment =<br/>schedule_matches_last_replay"]
  G2 --> L
  I --> M["публикуется с оговоркой:<br/>feedback_alignment =<br/>network_feedback_not_applied_to_last_replay"]
  K --> M
```

Различие между «сошлось» и «зациклилось» принципиально: повтор подряд означает, что
расписание перестало меняться; повтор через другие расписания означает, что система
ходит по кругу и предела не имеет. `converged_partial` — это сходимость при
неразрешённых парах (разрешена флагом `allow_partial_geometry`); `iteration_limit` и
`cycle_detected` публикуют результат, но с явной пометкой `feedback_alignment`, что
последнее сетевое расписание НЕ применено к последней физической записи.

## 3.5 Полный путь подробного режима

```mermaid
sequenceDiagram
  autonumber
  participant F as Фронтенд
  participant B as Backend
  participant G as Генератор
  participant W as Процесс фрагмента
  participant N as LIF-сеть

  F->>B: fragment-population-runs (source_ids)
  B->>G: /v1/fragment-population-executions
  G->>W: spawn
  W->>W: геометрия + HH-кабели на GPU (актив и контроль)
  W->>W: диагностика: пороги, тики, макс. мВ
  W->>N: расписание вынужденных входов
  N-->>W: спайки сети и подавление источников
  W-->>G: запись E1–REF + сеть + диагностика
  G-->>B: артефакты и манифест
  B-->>F: completed
  F->>B: population-feedback-runs (те же source_ids)
  B->>G: /v1/population-feedback-executions
  G->>W: итерации до сходимости расписаний
  W-->>F: coupled-events.bin, coupled-delta.bin
```

Фронтенд запускает эти два шага подряд автоматически: сначала физический фрагмент,
потом обратную связь. Между ними оператор не участвует, но результат первого шага
уже сохранён — если второй упадёт, запись E1–REF останется.

## 3.6 Затем вся сеть: прокси по фрагменту

Третий шаг подробного режима — `createFieldProxyFromFragment`: те же события
фрагмента подаются в LIF-сеть всей ЦНС с экспериментальным gain = 1 000 000. Это нужно,
чтобы увидеть, как локальное воздействие расходится по сети, но это по-прежнему
прокси: сеть не возвращает обратную связь в физические клетки.

```mermaid
flowchart LR
  A["фрагмент: 256 HH-клеток"] --> B["их события — вынужденные входы"]
  B --> C["LIF-сеть 166 700 узлов"]
  C --> D["события сети, разница с контролем"]
  D -.->|"НЕ возвращается"| A
```

Пунктир на схеме — самое важное место всего документа: в подробном режиме сеть не
влияет обратно на физические клетки. Замкнутый контур появляется только в полном
связном опыте.
