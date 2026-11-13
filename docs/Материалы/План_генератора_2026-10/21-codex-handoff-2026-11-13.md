# 21. Передача работы Codex: полный расчёт 166 700 нейронов за 120 с

Дата: 2026-11-13. Продолжение [20-full-population-2026-11-13.md](20-full-population-2026-11-13.md).

Документ — самодостаточное задание для следующего агента (Codex). Он описывает
цель, измеренное состояние, принятые решения, запрещённые направления, точные
команды воспроизведения и порядок приёмки.

---

## 1. Цель

**Посчитать все ~166 700 зарегистрированных сложных (компартментных) нейронов
MaleCNS end-to-end за 120 с** на текущем железе: RTX 3060 Laptop (6 ГиБ VRAM),
16 логических CPU, 16 ГиБ RAM. Модельное время — 10 мс при шаге 0,05 мс (200 шагов).

Цель 20 с из более ранних документов на этом железе **недостижима принципиально**
(см. раздел 4). Приёмка идёт по 120 с; всё, что ниже 268 с, требует смены алгоритма,
а не настройки параметров.

## 2. Где мы стоим сейчас (измерено, не оценено)

| величина | значение |
|---|---:|
| клеток | 166 699 (один ID без полной геометрии) |
| сегментов | 269 816 969 |
| батчей | 140 |
| **wall-clock end-to-end** | **419,9 с = 7,0 мин** |
| из них GPU solve | 309,8 с |
| хост-подготовка (перекрыта) | 110,0 с |
| rate_live | 174,2 млн сегменто-шагов/с |
| мс на клетку на проход | 2,52 |

Хронология: 64 ч -> 34 ч -> 24 мин (экстраполяция) -> **7,0 мин** (измерено).
От исходного боевого ядра (1482,7 с) это 3,5x; от 34 ч — 291x. Разрыв с целью 120 с: 3,5x.

## 3. Архитектура пути

Весь код — `R:\Aspa\generator\service\infrastructure\stimulation\experimental_gpu`
(модуль НЕ зарегистрирован как боевой решатель, но это реальный код сервиса, а не
скрипты в `.work`; оптимизации обязаны попадать именно сюда).

| файл | ответственность |
|---|---|
| `fast_prepare.py` | аутентифицированное чтение кэша, `iter_prepared_chunks`, `read_manifest`, `cells_from_chunk` |
| `fast_cable.py` | подготовка клетки без NEURON: `Params`, `prepare_chunk`, `PreparedChunk.as_gpu` |
| `reduced_tree.py` | `reduce_geometry(geometry, verify=True)` -> (geometry, report) |
| `reroot_tree.py` | `reroot_centre(parents, conductances, segment_nodes, centre=None)`, `centre_levels` |
| `tree_levels.py` | уровни Hines и группы детей: `parent_groups_by_level`, `batch_tree_layouts` |
| `batching.py` | `plan_batches(segment_counts, max_cells, max_padded_segments, max_padding_ratio)` |
| `warp_packing.py` | `pack_cell_major(trees, layouts, gates, initial_voltage)`, `CellMajor` |
| `hines_kernel.py` | `batched` (прод), `warp_batched` (варп на клетку, cell-major), `block_cell` |
| `batch_solver.py` | `build_cell_major`, `_solve_cell_major`, `solve_prepared_batch` |
| `population_replay.py` | `iter_cell_batches`, `solve_population` — трёхступенчатый конвейер |
| `hh_table.py`, `waveform.py`, `events.py`, `validation.py` | кинетика, стимул, события, проверки |

Сигнатуры:

- `PR.solve_population(metadata, stimulus_midpoint, rate_table, *, audited_sources, params,
  segment_budget, output_budget_bytes, dt_ms, window_steps, block_threads, reduce_trees,
  workers, limit, progress, check_cancelled, timing_sink, window_sink, window_cells,
  max_padding, max_cells, pool_cells, cell_warps, block_cell_segments, allow_table_clamp,
  prefetch, reroot, reduce_workers)`
- `batch_solver.solve_prepared_batch(cells, stimulus_midpoint, rate_table, *, output_budget_bytes,
  dt_ms, ..., cell_major=False, cell_warps=1, block_cell_segments=40000, cell_major_packed=None)`

Конвейер `solve_population` — три потока с очередями `prepared` (maxsize=prefetch) и
`waiting` (maxsize=1): продюсер читает+готовит+сокращает, упаковщик делает cell-major
колонки, потребитель запускает ядро. **Нельзя** совать упаковку в продюсер и нельзя
оставлять её перед запуском — оба варианта измерены и хуже (раздел 6).

## 4. Физический потолок

Ядро `warp_batched` насыщается на **2,0e8 live-сегменто-шагов/с** на реальной клетке
медианного размера (`probe-occ-sweep.py`, клетка 52: 944 сегмента, 993 узла, 372 уровня):

| батч (варпов) | rate_live | мкс/клетку |
|---:|---:|---:|
| 512 | 1,62e8 | 1161,8 |
| 1024 | 1,82e8 | 1033,3 |
| 2048 | 1,93e8 | 975,3 |
| 4096 | 1,99e8 | 942,2 |
| 8192 | 1,98e8 | 947,2 |

Физический пол: 269 816 969 сегментов x 199 шагов / 2,0e8 = **268 с** только ядра при
идеальном padding 1,0; 322-430 с при реальном 1,2-1,6. Цель 120 с требует 4,5e8
(2,2x выше потолка), цель 20 с — 2,7e9 (13x). Цифра 2,7e8 получена на синтетической
зависимой цепочке и на реальном дереве недостижима — не использовать в оценках.

Ограничитель — не барьеры и не ALU, а **тело уровневого обхода**: `probe-split-cost.py`
даёт 0,3348 с без обхода против 0,946 с с ним (=64 % времени), а `no_barrier` 0,9363 с —
сами `syncwarp` бесплатны. Ядро memory-bound: f32 даёт +9 % (`bench-fp32div.py`).

## 5. Принятые решения (не пересматривать без причины)

1. **Сокращение дерева включено** (`reduce_trees=True`): 67 % виртуальных узлов степени 2
   и 17 % бесполезных кончиков; 1,74x при 5,4e-13 отн. (3,5e-11 мВ абс. на 200 шагах).
2. **Re-root в центр включён** (`reroot=True`): 1,27x на сервисном пути (603 -> 475 с):
   меньше уровней у длинных тонких клеток.
3. **Warp-ядро на всё, кроме сверхширокого хвоста**: `probe-width-buckets.py` — warp
   выигрывает в каждом бакете до 32 768 сегментов (block_cell 0,55-0,74x); только бакет
   32 768+ выигрывает от `block_cell` (2,55x при 256 потоках), и там 60 клеток / 2,7 млн
   сегментов. Диспетчеризация — по `block_cell_segments`.
4. **cell_warps = 4** на блок: solve_cell_major 332 -> 271 с.
5. **Параллельный декод**: 8 воркеров x 4 нити numba (насыщается на 4 нитях).
6. **Пул клеток 12 000**, дренируется ЦЕЛИКОМ (любое правило частичного сброса рождает
   батчи по 1-3 клетки).
7. **slim-полезная нагрузка пула** (`np.ascontiguousarray(...).copy()` в `_narrow`): без неё
   пул 6000+ роняет прогон, потому что вид на массив держит весь декодированный чанк.

## 6. Отрицательные результаты — НЕ ПОВТОРЯТЬ

| гипотеза | результат | почему |
|---|---|---|
| Несколько клеток в одном варпе (G=2,4,8) | 0,76x / 0,51x / 0,26x, бит-в-бит | падает только число варпов, число БАРЬЕРОВ не меняется |
| Плоский обратный BFS-порядок вместо уровней | 1,10-1,12x | не главный рычаг |
| f32 для всего ядра | +9 % | ядро memory-bound |
| exp() через таблицу на батче 2048 | 0,96-0,995x | в насыщенном режиме выигрыша нет |
| `__syncwarp` вместо `syncthreads` | бит-в-бит, медленнее | ядро не барьерно-связано |
| reduce в пуле потоков (2-6) | 0,4-0,5x | GIL/конкуренция |
| reduce в пуле процессов (2-8) | 0,32-0,40x | пиклинг дороже работы |
| NUMBA_NUM_THREADS 2 -> 8 при 8 воркерах | без выигрыша | декод насыщается на 4 нитях |
| Пул 48 000 клеток | хуже пула 12 000 | медленно наполняется, GPU простаивает |
| max_padding 1,15-1,3 | 140 -> 207-385 батчей, wall растёт | мелкие батчи дороже padding |
| Упаковка в потоке продюсера | 475 -> 555 с | продюсер и упаковка сериализуются |
| Батчи 2200-3000 клеток (full23) | wall 658 с | ядро быстрее, но prepare/reduce/select раздуваются |
| Прототипы `probe-*` / `bench-*` в `.work` | — | НЕ переносить в сервис как есть |

## 7. Где остаётся время (140 батчей, solve 309,8 с)

| класс батчей | батчей | время |
|---|---:|---:|
| < 200 клеток | 52 | 43,8 с |
| 200-999 | 20 | 49,0 с |
| >= 1000 | 68 | 217,0 с (на 150 661 клетку) |

Худшие: n=138 (1261 клетка, widest 18 907) — 10,5 с; n=130 (1020, 19 951) — 10,0 с;
n=1 (613 клеток, widest 41) — 8,8 с чистых накладных на батч; n=139 (141 клетка,
widest 68 925) — 4,9 с. Плюс 110 с простоя GPU и 36 с аллокаций/передач.

Три рычага по ожидаемой отдаче:

1. **Мелкие батчи (43,8 с)**: не padding, а склейка хвостов в один батч с общим ядром
   и маской (клетки разной ширины в одном запуске).
2. **Простой GPU 110 с**: продюсер не успевает; decode+reduce = 62 с на 48 тыс. клеток
   при 8 воркерах — близко к пределу хоста.
3. **Сверхширокий хвост**: 4 клетки > 65 536 сегментов идут block-per-cell по ~5 с;
   всего 60 клеток > 32 768 (2,7 млн сегментов) — хвост это 2 % сегментов.

## 8. Воспроизводимость зависит от свободной памяти хоста

| прогон | конфиг | free RAM | wall |
|---|---|---:|---:|
| smoke3 | 6 воркеров, пул 12000, numba 2 | ~6 ГБ | **419,9 с** |
| final40 | тот же | 1,7 ГБ | 994,2 с |
| final41 | 4 воркера, пул 6000, numba 2 | 0,9 ГБ | 923,6 с |

final41: decode 234 с (в изолированной пробе 27 с), reduce 315 с, allocation 148 с,
final transfer 54 с, solve_cell_major 322 с; Pages/sec = 21 220 — активный своп,
16 ГиБ физической при 31,8 ГиБ закоммиченной.

**Правило приёмки: бенчмарк логирует свободную RAM хоста и не запускается при < 5 ГБ.**

## 9. Как воспроизвести

| хост | контейнер | содержимое |
|---|---|---|
| `R:\Aspa\generator` | `/source` (ro) | код сервиса |
| `R:\Aspa\.work\connectome-routing-20261028` | `/out` | драйверы, логи, отчёты |
| `R:\Aspa\.data\male-cns\geometry-cache-v1-zlib` | `/data/cache` (ro) | 2605 чанков, 2,764 ГБ |
| `R:\Aspa\.data\male-cns\morphology-index` | `/data/index` (ro) | verified-bounds-v2 |
| `R:\Aspa\.work\generator-implementation\fresh-connectome\graph` | `/data/graph` (ro) | граф |

Драйвер `/out/production-bench/e2e-service-ab.py`, argv:
`<limit> <segment_budget> <workers> <window_cells> <max_padding> <max_cells> <pool_cells>
<block_cell_segments> <prefetch> [reroot|noreroot] [cell_warps] [reduce_workers]`.

Лучшая конфигурация (419,9 с): `0 24000000 6 4096 3.0 3000 12000 40000 1 reroot 4 1`.

```bat
docker run --rm --gpus all --memory 13g -e PYTHONPATH=/source -e NUMBA_NUM_THREADS=2 ^
  -v R:/Aspa/generator:/source:ro ^
  -v R:/Aspa/.work/connectome-routing-20261028:/out ^
  -v R:/Aspa/.data/male-cns/geometry-cache-v1-zlib:/data/cache:ro ^
  -v R:/Aspa/.data/male-cns/morphology-index:/data/index:ro ^
  -v R:/Aspa/.work/generator-implementation/fresh-connectome/graph:/data/graph:ro ^
  aspa-generator:gpu-demo-compat-20261109 ^
  /app/.venv/bin/python -u /out/production-bench/e2e-service-ab.py ^
  0 24000000 6 4096 3.0 3000 12000 40000 1 reroot 4 1 ^
  > R:/Aspa/.work/connectome-routing-20261028/production-bench/e2e-run.log 2>&1
```

**Про образ.** В `aspa-generator:gpu-demo-compat-20261109` пакета `experimental_gpu` НЕТ
(только README, `__init__`, events, waveform), поэтому `PYTHONPATH=/source` и монтирование
`R:/Aspa/generator` в `/source` обязательны; монтирование в `/gen` бесполезно —
`/app/service` затенит путь. Python: `/app/.venv/bin/python`, numba 0.67.0, numpy 2.2.6.
pytest в образе НЕТ — тесты идут через шим `/out/production-bench/run-tests.py`.

Пробы (в `/out/production-bench/`): `probe-occ-sweep.py` (потолок), `probe-split-cost.py`
(разложение ядра), `probe-level-occupancy.py` (занятость уровней), `probe-width-buckets.py`
(выбор ядра), `probe-multicell.py` (G клеток в варпе), `sim-tail.py` (хвост по ширине),
`analyze-batches2.py` (разложение по батчам), `check-reduce.py` (точность сокращения).

## 10. Порядок приёмки

1. Поднять Docker-демон: на 2026-11-13 13:40 он был недоступен
   (`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`),
   поэтому последний прогон этой сессии не состоялся.
2. Зафиксировать free RAM хоста (нужно >= 5 ГБ).
3. Smoke на 2000 клетках, сверить `ms_per_cell` с 2,5 мс (допуск 20 %).
4. Полный прогон: `cells 166 699`, `segments 269 816 969`, сравнить wall с 419,9 с.
5. Численная эквивалентность: `check-reduce.py` (5,4e-13 отн.) и
   `check-kernel-equivalence.py` / `check-cellmajor-solver.py` (бит-в-бит).
6. Записать результат в новый документ 22-* и обновить таблицу в
   [18-full-neuron-performance-2026-11-11.md](18-full-neuron-performance-2026-11-11.md)
   раздел 7.

## 11. Границы вывода

- Это **независимый** реплей клеток под общим стимулом, **не сетевой расчёт** и не
  обратная связь: синаптическое взаимодействие не моделируется.
- Одна клетка из 166 700 упирается в границу диапазона таблицы напряжений
  (`range_flags` = 1); так было и в исходном прогоне.
- Сверка с NEURON выполнена на трёх морфологиях (макс. 8,16e-9 мВ); полная сеть не сверялась.
- Биологическая валидация не выполнялась и не заявляется.

## 12. Ссылки

- Базовая производительность: [18-full-neuron-performance-2026-11-11.md](18-full-neuron-performance-2026-11-11.md)
- Первый сквозной прогон: [19-end-to-end-population-2026-11-12.md](19-end-to-end-population-2026-11-12.md)
- Полный прогон: [20-full-population-2026-11-13.md](20-full-population-2026-11-13.md)
- Открытые критерии: [TODO.md](TODO.md)
- Скрипты и логи: `R:\Aspa\.work\connectome-routing-20261028\production-bench`