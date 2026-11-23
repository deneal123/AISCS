# 01. Общая архитектура: путь одного опыта

## 1.1 Компоненты и кто за что отвечает

```mermaid
flowchart TB
  subgraph UI["Фронтенд · React · :8095"]
    Screen["Экран записи<br/>FragmentPopulationRecording.jsx"]
    Mode{"Режим расчёта"}
    Hooks["Хуки запуска и опроса<br/>useDirectNetworkProxy<br/>usePopulationFeedback<br/>useFullPopulationFeedback"]
  end

  subgraph API["Backend · FastAPI · :8094"]
    Rest["simulations/api.py<br/>приём запроса"]
    Manifest["Проверка манифеста<br/>manifests/*.py"]
    Route{"Определение вида опыта<br/>tasks.py:381-452"}
    Queue["Celery · очередь simulation<br/>concurrency=1"]
    Poll["Опрос статуса и выдача артефактов"]
  end

  subgraph GEN["Генератор · FastAPI · :8090"]
    Exec["presentation/http.py<br/>/v1/*-executions"]
    Child["Изолированный процесс<br/>mp spawn + progress.json"]
    Engine{"Движок расчёта"}
  end

  subgraph CALC["Расчётное ядро"]
    Field["Поле по SWC<br/>point_field / network_field"]
    LIF["LIF-сеть ЦНС<br/>connectome/kernel.py"]
    HH["HH-кабели на GPU<br/>experimental_gpu/*"]
  end

  PG[("PostgreSQL<br/>запуски и состояния")]
  Redis[("Redis<br/>события прогресса")]
  FS[("Хранилище<br/>артефакты и хеши")]

  Screen --> Mode
  Mode --> Hooks
  Hooks -->|REST| Rest
  Rest --> Manifest --> Route
  Route --> Queue
  Queue -->|HTTP POST| Exec
  Exec --> Child --> Engine
  Engine --> Field
  Engine --> LIF
  Engine --> HH
  Queue --> PG
  Poll --> PG
  Poll --> FS
  Rest --> Redis
  Redis -->|"WebSocket прогресс"| Hooks
  FS --> Poll --> Hooks
  Child -->|"progress.json"| Poll
```

Роли разделены жёстко. Backend отвечает за авторизацию, проверку входов, очередь,
статус и публикацию; генератор — только за научный расчёт и временные файлы своей
попытки. У генератора нет ни PostgreSQL, ни брокера, ни docker-сокета: если он упадёт,
backend останется с непрочитанной попыткой, а не с испорченной базой.

## 1.2 Как backend выбирает, что запускать

Вид опыта определяется не полем `kind`, а составом полезной нагрузки
(`R:/Aspa/backend/service/services/simulations/tasks.py:381-452`):

```mermaid
flowchart TD
  P["payload запроса"] --> Q1{"source_run_id?"}
  Q1 -->|да| R1["replay<br/>/v1/replay-executions"]
  Q1 -->|нет| Q2{"source_cells и replay_ids?"}
  Q2 -->|да| R2["field_graph<br/>/v1/field-graph-executions"]
  Q2 -->|нет| Q3{"gain, waveform,<br/>coordinate_frame = male-cns-v1.0-native-um?"}
  Q3 -->|да| R3["field_proxy — БЫСТРЫЙ расчёт<br/>/v1/field-proxy-executions"]
  Q3 -->|нет| Q4{"source_ids и max_distance_um?"}
  Q4 -->|да| R4["fragment_population — ПОДРОБНЫЙ<br/>/v1/fragment-population-executions"]
  Q4 -->|нет| Q5{"только graph_manifest_sha256<br/>и simulation?"}
  Q5 -->|да| R5["independent_population<br/>/v1/independent-population-executions"]
  Q5 -->|нет| Q6{"excitatory, inhibitory,<br/>max_source_distance_um,<br/>без source_package_sha256?"}
  Q6 -->|да| R6["full_feedback — ПОЛНАЯ ЦНС<br/>/v1/full-population-feedback-executions"]
  Q6 -->|нет| Q7{"source_package_sha256 и target_id?"}
  Q7 -->|да| R7["population_target"]
  Q7 -->|нет| R8["population_feedback<br/>или /v1/executions"]
```

Порядок проверок важен: `full_feedback` — самый широкий набор полей, поэтому он
проверяется после узких. Любая правка манифеста обязана сохранять это свойство, иначе
запрос полного опыта уедет в ветку фрагмента.

## 1.3 Жизненный цикл одного запуска

```mermaid
sequenceDiagram
  autonumber
  participant U as Оператор
  participant F as Фронтенд
  participant B as Backend
  participant C as Celery
  participant G as Генератор
  participant W as Изолированный процесс
  participant D as Диск

  U->>F: нажимает «Запустить»
  F->>B: POST /simulator/runs/.../field-proxy-direct<br/>или /full-population-feedback-runs
  B->>B: проверка манифеста и прав владельца
  B->>D: запись строки запуска (queued)
  B-->>F: id запуска
  B->>C: задача simulation
  C->>G: POST /v1/...-executions
  G->>G: валидация контракта (422 при отказе)
  G->>W: spawn отдельного процесса
  W->>D: progress.json (атомарно)
  F->>B: опрос каждые 3 с + WebSocket
  B->>D: чтение progress.json и пересылка
  B-->>F: preparing → running → publishing
  W->>D: артефакты + manifest.json с хешами
  W-->>G: код возврата
  G-->>C: статус завершён
  C->>B: сохранение результата
  B-->>F: completed, ссылки на файлы
  F->>U: график и файлы результата
```

Статусы одинаковы для всех видов опыта: `queued → preparing → running → publishing`,
плюс `cancelling` при отмене. Фронтенд считает активными ровно эти пять состояний и
прекращает опрос на любом другом.

## 1.4 Три режима с точки зрения физики

```mermaid
flowchart LR
  subgraph FAST["Быстрый · LIF-прокси"]
    F1["Поле по SWC"] --> F2["одно число на клетку"] --> F3["LIF-сеть 166 700 узлов"]
  end
  subgraph DETAIL["Подробный · фрагмент"]
    D1["≤ 256 клеток"] --> D2["HH-кабели на GPU"] --> D3["события → расписание"]
    D3 --> D4["прокси всей сети по фрагменту"]
  end
  subgraph FULL["Полная ЦНС · экспериментальный"]
    A1["все 166 700 клеток"] --> A2["HH-кабели на GPU"] --> A3["расписание по всей сети"]
    A3 --> A4["повтор до сходимости"]
    A4 --> A5["контрольная ветвь"]
  end
```

Ключевое различие: быстрый режим не решает уравнение кабеля вообще (одна точка на
клетку), подробный решает его для сотен клеток, полный — для всех. Поэтому время
растёт не пропорционально числу клеток, а пропорционально числу сегментов: у полной
ЦНС это 270 009 259 сегментов.

## 1.5 Где что лежит

| Слой | Каталог |
| --- | --- |
| Фронтенд | `R:/Aspa/frontend/src/features/simulator/` |
| Backend API и задачи | `R:/Aspa/backend/service/services/simulations/` |
| HTTP генератора | `R:/Aspa/generator/service/presentation/http.py` |
| Прикладные сценарии | `R:/Aspa/generator/service/application/{field,population,feedback,replay}/` |
| GPU-ядро | `R:/Aspa/generator/service/infrastructure/stimulation/experimental_gpu/` |
| Контракты | `R:/Aspa/generator/service/domain/contracts/` |
