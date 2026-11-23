# 02. Простой расчёт: поле по SWC и LIF-прокси всей сети

Это режим «Быстрый» на экране записи. Он отвечает на вопрос «что примерно произойдёт
в сети целиком», не решая ни одного уравнения кабеля. Физики клетки здесь нет:
каждая клетка — один узел с одной переменной напряжения.

## 2.1 Что делает оператор и что уходит на сервер

```mermaid
flowchart TD
  A["Оператор ставит E1, REF, STIM+, STIM− и выбирает режим «Быстрый»"] --> B["Проверяются только два контакта:<br/>source_um = STIM+ и return_um = STIM−"]
  B --> C["E1 и REF в быстром расчёте НЕ участвуют<br/>(комментарий в коде: E1 and REF do not<br/>contribute to the fast network-only calculation)"]
  C --> D["POST /simulator/runs/{id}/field-proxy-direct"]
  D --> E["payload: request_id, simulation,<br/>graph_manifest_sha256, seed,<br/>gain = 1 000 000,<br/>allow_partial_geometry, allow_missing_curvature,<br/>allow_contact_exclusion = false"]
```

Отсюда первое важное ограничение: быстрый режим не даёт записи E1–REF. Если нужна
запись от электрода, это подробный или полный режим.

## 2.2 Два этапа внутри генератора

```mermaid
flowchart TB
  S["execute_field_proxy<br/>R:/Aspa/generator/service/application/field/proxy_execution.py:25"] --> E1{"compute_field?"}
  E1 -->|да| F1["Этап 1. Поле<br/>compute(ids, directories, field_path, configuration)<br/>по графе клеток ЦНС"]
  F1 --> F2["Для каждой клетки: бипотенциал по её SWC<br/>point_field.bipolar_potential_mv"]
  F2 --> F3["Сводка network_field: max_abs_curvature_signed_mv_per_um2<br/>status: ok | partial_geometry"]
  E1 -->|нет| V1["Этап 1 пропущен:<br/>поле читается из готового файла"]
  F3 --> V2["verified_descriptors: проверка подписи поля<br/>и совпадения configuration"]
  V1 --> V2
  V2 --> N1["Этап 2. Сеть<br/>run_field_proxy(graph, descriptor, waveform, gain, seed)"]
  N1 --> N2["drive_reference = descriptor × gain"]
  N2 --> N3["LIF-ядро kernel.advance<br/>166 700 узлов, шаг 1 мс"]
  N3 --> O["Артефакты: network.npz, network-events.bin,<br/>network-control-events.bin, state-response.bin,<br/>metadata.json, field-proxy-preview.json"]
```

## 2.3 Ядро LIF: что именно интегрируется

`R:/Aspa/generator/service/infrastructure/connectome/kernel.py:11` — это точный код,
перенесённый из Fly Arena, и он намеренно простой:

```mermaid
flowchart TB
  T["такт t (1 мс)"] --> A["current = current × exp(-1/5) + queue[slot]"]
  A --> R{"в рефрактерности?"}
  R -->|да| R1["voltage = 0, refractory -= 1, пропуск"]
  R -->|нет| V["voltage = max(-30, exp(-1/20) × voltage<br/>+ (1 - exp(-1/20)) × (drive + current))"]
  V --> TH{"voltage ≥ 7.0?"}
  TH -->|да| SP["voltage = 0, refractory = 2 тика,<br/>спайк в счётчик,<br/>в очередь доставки через 2 тика добавить вес"]
  TH -->|нет| NEXT["следующий такт"]
  SP --> NEXT
```

Три числа задают всю динамику: постоянная мембраны 20 мс, постоянная тока 5 мс, порог
7.0 в безразмерных единицах. Вес связи — `counts × signs × 0.075`, где `counts` —
число синапсов между клетками, `signs` — знак (возбуждающий/тормозной). Задержка
доставки фиксирована: 2 тика. Рефрактерность — 2 тика.

## 2.4 Почему это «прокси», а не модель

```mermaid
flowchart LR
  P1["поле считается честно:<br/>реальный SWC, реальные координаты"] --> P2["но сводится к ОДНОМУ числу<br/>на клетку"]
  P2 --> P3["значит форма дендрита,<br/>распространение по кабелю<br/>и локальные токи потеряны"]
  P3 --> P4["gain = 1 000 000 —<br/>экспериментальный множитель,<br/>не откалиброван"]
  P4 --> P5["вывод: это различимость отклика,<br/>а не физиология"]
```

В коде это сказано прямо: `metadata.json` получает поле
`interpretation: 'uncalibrated LIF events; not measured neural activity'`, а
`network_weight_gain: 0.075` записывается в метаданные, чтобы результат нельзя было
прочитать как измерение.

## 2.5 Управляющие флаги и когда расчёт отказывает

| Флаг | Что разрешает | Если выключен |
| --- | --- | --- |
| `allow_partial_geometry` | клетки с неполной геометрией | отказ `field_partial_geometry` |
| `allow_missing_curvature` | клетки без кривизны | отказ `field_missing_curvature` |
| `allow_contact_exclusion` | контакты, исключённые из поля | отказ `field_contact_exclusion` |
| `capture_delta` | второй прогон с нулевым стимулом | нет `state-delta.bin` |

Флаги не «чинят» данные: они разрешают опубликовать результат с явной пометкой
`partial_geometry` в квитанции. Разница между «посчитано» и «посчитано частично»
видна в манифесте, а не скрыта.

## 2.6 Что получает оператор

```mermaid
flowchart LR
  R["результат быстрого расчёта"] --> A["network-events.bin — события по 1 мс"]
  R --> B["network-control-events.bin — та же сеть без стимула"]
  R --> C["state-response.bin и state-delta.bin — разница состояний"]
  R --> D["field-proxy-preview.json — сводка для графика:<br/>spikes_by_ms, control_spikes_by_ms,<br/>spike_count, active_neurons"]
  R --> E["metadata.json — хеши поля, ядра, весов;<br/>интерпретация и seed"]
```

Контрольный прогон (нулевой стимул) идёт тем же ядром с тем же seed, поэтому разница
`active − control` — это вклад стимула, а не случайность инициализации.
