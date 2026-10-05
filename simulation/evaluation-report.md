# Проверка кандидатов для генератора данных

Срез исходников: 4 октября 2026. Испытания и редакция отчёта: 5 октября 2026.

## Текущий результат

- Подключены 32 уникальных репозитория; 19 используют уже зарегистрированный commit. Остальные закреплены по доступному upstream на датированный срез.
- Адреса `NSSIL/ScaleBreak-FlyVis` и `smpuglie/Pugliese_cpg_2025` учтены как переименования. Дубликаты не подключены.
- Прочитаны зависимости, лицензии и штатные точки входа; синтаксически разобраны 1238 Python-файлов. Это проверка исходников, а не функциональное воспроизведение.
- Гибридный поиск и граф проверены на `g-56b4c46e48ad7a8b5db92c99`: четыре сохранённых запроса выполнены в режиме `hybrid`, без ошибок; граф ST106 содержит четыре узла и три связи. Индекс не перестраивался.
- Контейнеры базы остановлены после проверки для освобождения памяти. Их тома и поколение сохранены; повторный запуск допускается после проверки ресурса.
- Вычислительные сценарии ограничены запасом RAM. Успешной установки, полного коннектома или биологической валидации из предварительного допуска не следует.
- Испытания возобновлены по порядку ID. Принятых установок: 4; штатных тестовых профилей: 2; CLI/smoke: 3; полностью завершённых функциональных профилей: 1. У 20 кандидатов подготовлены CPU-профили, у 12 записаны необходимые среды или входы.
- SIM-001 Fly Arena: установлены зависимости, `pip check` и семь штатных тестов прошли. Для Linux подготовлены Mesa/EGL, для pytest на Windows-монтировании применён захват `sys`. Body-demo seeds 1/2/3 завершили по 3 секунды (300 строк каждый; 26,2–26,9 секунды wall time). Пустые нейронные поля сохранены как неприменимые к body-demo.
- Повторяемость body-demo seed 1 подтверждена двумя завершёнными попытками: все 300 численных строк совпадают после исключения wall-time. Параметры CLI, Python, MuJoCo и платформа совпадают; отличается каталог экспорта. Основание: `functional_evidence` в реестре и квитанция проверки CSV/JSON в `.work/`.
- В первоначальной партии дополнительный повтор body-demo seed 1 остановлен защитой RAM после 1,62 секунды. Его 162 строки совпали с началом завершённого seed 1. Этот исторический профиль сохраняет `blocked`; итог последующих проверок полного коннектома приведён ниже. Пиковая память прерванной попытки: 746942464 байта; прекращение собственного контейнера подтверждено. Точное минимальное чтение RAM этой попытки не записывалось; для последующих попыток оно добавлено в журнал.
- Проверена реальная остановка собственного контейнера при падении запаса памяти; чужие контейнеры не останавливались.
- Архитектура генератора не выбрана. Научные статусы: **35/43, G0_REVISE, saturation=false**, 15 неранжированных решений.
- Проверки подготовленного инструмента: Ruff без ошибок; pytest — 10 тестов допуска, закрепления commit, ограничения путей, отмены и остановки очереди. Проверка целостности подтвердила 32 чистых checkout, Git-ссылки и сохранность SHA256 281 защищённого файла. JSON, относительные ссылки, LF и `git diff --check` проверены. Эти результаты не относятся к штатным тестам симуляторов.

## Реестр и результаты

Точные commits, ресурсы ST, научные карточки и хеши лицензий: [registry.json](registry.json). Текущие оценки и первичные маршруты данных: [assessment.json](assessment.json). Команды отдельных сред: [profiles.json](profiles.json).

| ID | Репозиторий на проверенном commit | Назначение | Лицензия исходников | Вычислительный результат |
|---|---|---|---|---|
| SIM-001 | [artem-x-meta/fly-arena](https://github.com/artem-x-meta/fly-arena/tree/12f48c702ed170b5bdc4643afa7ce65e952b353d) | embodied | MIT | passed_tested_scenarios: see run receipt |
| SIM-002 | [chaobrain/fitting_drosophila_whole_brain_spiking_model](https://github.com/chaobrain/fitting_drosophila_whole_brain_spiking_model/tree/f1389ba8b0e7c9f4059d2538b6b799c3e88342ee) | neural-fitting | not established | partial_missing_data: see run receipt |
| SIM-003 | [cnqso/infinite-sugar](https://github.com/cnqso/infinite-sugar/tree/fdbbd866b203a709a164970b0a8996108edd57a5) | neural | not established | passed_tested_scenarios: see run receipt |
| SIM-004 | [cooneypc4/larval_escape_manuscript](https://github.com/cooneypc4/larval_escape_manuscript/tree/c927d42b7234add7df3ead576a8effc02facce18) | author-analysis | not established | blocked_missing_runtime_and_data: see run receipt |
| SIM-005 | [emebeiran/connconstr](https://github.com/emebeiran/connconstr/tree/f5f397b88f8dd5c2a5c13558ce6039194a284586) | method-comparator | not established | passed_tested_scenarios: see run receipt |
| SIM-006 | [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain/tree/a3db62f9436074e485c0278290c2164ed6150808) | neural | GPL; variant requires review | blocked: host_memory_reserve |
| SIM-007 | [erankopel/maleCNS-depth](https://github.com/erankopel/maleCNS-depth/tree/e80dcf643beefff08afd936a741ac8cc50723cb4) | connectome-preparation | MIT | blocked: host_memory_reserve |
| SIM-008 | [flyconnectome/2025malecns](https://github.com/flyconnectome/2025malecns/tree/67767d2233657983993ff6c2be48e836a935863c) | connectome-preparation | not established | blocked: Notebook/data release, not a simulator; supplementary tables must be registered before numerical replay |
| SIM-009 | [gauravvvvvvvvvv/flybox](https://github.com/gauravvvvvvvvvv/flybox/tree/5880d221e21b1f3385b7246a6ffc3b2cf0029c2c) | browser-neural | Apache-2.0 | blocked: host_memory_reserve |
| SIM-010 | [hsseung/OpticLobe.jl](https://github.com/hsseung/OpticLobe.jl/tree/3352e97c37b0f96ab08f27b70b4420f3d4ac2726) | connectome-preparation | MIT | blocked: Julia scientific analysis requires its Julia lock environment and matching optic-lobe datasets |
| SIM-011 | [htem/BANC-project](https://github.com/htem/BANC-project/tree/e31a2e26b9937dca72e5ca1c1960df6454d76114) | connectome-preparation | not established | blocked: R BANC analysis depends on a materialisation, data exports and server credentials; it is not an executable fly simulator |
| SIM-012 | [htem/FANC_auto_recon](https://github.com/htem/FANC_auto_recon/tree/89d9769457583051e3ec9ec7b34a5f3575537bf5) | connectome-preparation | GPL; variant requires review | blocked: host_memory_reserve |
| SIM-013 | [jajmcallister/Conn_ESN_Paper](https://github.com/jajmcallister/Conn_ESN_Paper/tree/55b9069b919951c39dfc3a342b7b31e6cb575838) | method-comparator | not established | blocked: Julia 1.11 ESN experiment requires weight matrices and the author environment, not a body simulator |
| SIM-014 | [JNLiew/flylif_orientation_maps](https://github.com/JNLiew/flylif_orientation_maps/tree/d73b18712579c969feba625ecfd3df52f4d328f4) | neural | not established | blocked: host_memory_reserve |
| SIM-015 | [legacyindiesubmissions-ai/claude-fly](https://github.com/legacyindiesubmissions-ai/claude-fly/tree/3a035275148e97539711728422548bffe2a77566) | embodied | MIT | blocked: Legacy FlyGym API coupling and pretrained LFS weights need resolution before an offline embodied run |
| SIM-016 | [MakazhanAlpamys/soup-connectome](https://github.com/MakazhanAlpamys/soup-connectome/tree/40aa07f87995a7061f75f92f8ddd0465ede89577) | neural | not established | blocked: host_memory_reserve |
| SIM-017 | [murthylab/flywire-network-analysis](https://github.com/murthylab/flywire-network-analysis/tree/ee4944c03429edf857a6b10bcf98bea7dcef35b8) | connectome-preparation | MIT | blocked: Linux graph-tool and FlyWire v630 data/cluster analyses require a dedicated graph-tool environment |
| SIM-018 | [nalin-dhiman/Connectome-Constrained-Neural-Networks](https://github.com/nalin-dhiman/Connectome-Constrained-Neural-Networks/tree/336e0d12a6edd92a7340cfffb71985a3879055ce) | neural | MIT | blocked: host_memory_reserve |
| SIM-019 | [nalin-dhiman/ScaleBreak-FlyVis](https://github.com/nalin-dhiman/ScaleBreak-FlyVis/tree/24c87489efdca64970ecbe93efc683b68f778cdf) | method-comparator | not established | blocked: host_memory_reserve |
| SIM-020 | [NeLy-EPFL/flygym](https://github.com/NeLy-EPFL/flygym/tree/38c8ec61034cd59bc5ba0de20688d4a3c0000d60) | body-environment | Apache-2.0 | blocked: host_memory_reserve |
| SIM-021 | [NeLy-EPFL/flygym-gymnasium](https://github.com/NeLy-EPFL/flygym-gymnasium/tree/d285260a1c8a7b3494150cd1590f2c9fe4b5e06b) | body-environment-compatibility | Apache-2.0 | blocked: host_memory_reserve |
| SIM-022 | [Neuromorphicism/fly-brain-snntorch](https://github.com/Neuromorphicism/fly-brain-snntorch/tree/fe55fb0cff275a2b6b54926524c8d831838e32fc) | neural | MIT | blocked: host_memory_reserve |
| SIM-023 | [nftechie/doomfly](https://github.com/nftechie/doomfly/tree/71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33) | embodied-game | MIT | blocked: Native C++ MaleCNS/ViZDoom engine requires a compiled toolchain, pinned game assets and full graph |
| SIM-024 | [philshiu/Drosophila_brain_model](https://github.com/philshiu/Drosophila_brain_model/tree/91bdd1e7dcf193f3e7ca5a8933497fcef63b7960) | neural | MIT | blocked: host_memory_reserve |
| SIM-025 | [rdarie/modular-bionic-interface-2026](https://github.com/rdarie/modular-bionic-interface-2026/tree/604d17fe1d39a6618fd8f26694922a823aeed8c8) | human-neural-interface-comparator | MIT | blocked: host_memory_reserve |
| SIM-026 | [seung-lab/FlyConnectome](https://github.com/seung-lab/FlyConnectome/tree/9b1790b5553082e1f57921790564c7aae7c9c99a) | connectome-preparation | not established | blocked: CAVE/cloudvolume tutorials require credentials or reachable public routes; preparation utility, not simulator |
| SIM-027 | [smpuglie/Pugliese_2026](https://github.com/smpuglie/Pugliese_2026/tree/10e7661bf414ba7b4c2edf795cd36d0f878c17c0) | motor-cpg | not established | blocked: host_memory_reserve |
| SIM-029 | [snedea/flybrain](https://github.com/snedea/flybrain/tree/9191824d17871b7851645782d53d23f213ddb938) | browser-neural | MIT | blocked: host_memory_reserve |
| SIM-030 | [Stavros963/fcta](https://github.com/Stavros963/fcta/tree/af8e451d9010294c185b966c953616b212f0294c) | connectome-analysis | MIT | blocked: Public repository contains sealed results, verify.py, seeds and lock; simulation pipeline explicitly withheld pending publication |
| SIM-031 | [TuragaLab/flyvis](https://github.com/TuragaLab/flyvis/tree/92b3845cc426dd309a1a0e1b3890156c42e14021) | visual-neural | MIT | blocked: host_memory_reserve |
| SIM-032 | [TuragaLab/wormvae](https://github.com/TuragaLab/wormvae/tree/15b58bff08bdf4eb04709434d766fca6835d7d79) | other-organism-comparator | not established | blocked: Author pins Python 3.6/PyTorch 1.8/numpy 1.16; a separate legacy image plus worm recordings is required |
| SIM-033 | [YijieYin/connectome_data_prep](https://github.com/YijieYin/connectome_data_prep/tree/a4df3b0d5345d2a34dac813f897d8427f6a6eb45) | connectome-preparation | not established | blocked: Data preparation requires selected dataset exports plus connectome_interpreter dependency; no generic data-free simulator entry point |

## Данные и научные границы

| ID | Проверенная постановка или необходимый вход |
|---|---|
| SIM-001 | MaleCNS; body-demo does not load the graph |
| SIM-002 | FlyWire v630/v783 and figshare activity; author preprocessed files required |
| SIM-003 | Author FlyWire export; supplied motor patterns coexist with neural readouts |
| SIM-004 | Larval escape behaviour and SCAPE muscle recordings; analysis only |
| SIM-005 | Teacher/student networks; Zenodo 16618353 figure data |
| SIM-006 | FlyWire v783 default; separate v630 paper scenario |
| SIM-007 | MaleCNS; confirmatory inputs have frozen MD5 and graph SHA256 |
| SIM-008 | MaleCNS supplemental exports; thresholds alter neuron/edge counts |
| SIM-009 | 166700 neurons; 25088107 edges; external export commit 03358c075000af5379e405b244dd31f1a0fd1401 |
| SIM-010 | Optic-lobe connectivity and Julia paper data; analysis only |
| SIM-011 | BANC materialisations v626/v850/v888; must match the selected scenario |
| SIM-012 | FANC data access and coordinate transforms; reconstruction/preparation |
| SIM-013 | Author ESN weight matrices and task inputs; Julia 1.11 |
| SIM-014 | FlyWire visual LIF model; explicit author data files required |
| SIM-015 | FlyWire v783 and plastic LFS weights; legacy FlyGym imports |
| SIM-016 | 4-neuron native fixture versus separate MaleCNS v1.0 Feather/SCX scenario |
| SIM-017 | FlyWire v630; graph-tool network analyses, not neural dynamics |
| SIM-018 | Connectome-constrained visual network and figure reproduction data |
| SIM-019 | Pretrained FlyVis responses and visual scale stimuli; comparator |
| SIM-020 | FlyGym 2.1.0; body/physics assets, no built-in whole-brain connectome |
| SIM-021 | FlyGym Gymnasium 1.3.2; separate import namespace and MuJoCo 3.2.7 |
| SIM-022 | FlyWire v630; sparse default (~280MB author estimate), dense alternative (~60GB) |
| SIM-023 | MaleCNS, compiled engine and ViZDoom; game damage is not biological nociception |
| SIM-024 | FlyWire v630 default; neuronal activation/silencing, no body/environment |
| SIM-025 | Benchtop and neural-interface recordings from OSF 9hxwe; not an ECAP forward simulator |
| SIM-026 | CAVE/cloudvolume FlyWire access tutorials; no simulator |
| SIM-027 | VNC/JAX model; exact lineage of the four S740 matrices still unresolved |
| SIM-029 | FlyWire FAFB v783 author binary; reduced legacy tests are a separate scenario |
| SIM-030 | Sealed larval-connectome result bundle; complete numerical pipeline not public at this pin |
| SIM-031 | Visual-system DMN and pretrained ensemble; not a whole-body/whole-brain simulator |
| SIM-032 | C. elegans latent model; different organism, Python3.6/PyTorch1.8 environment |
| SIM-033 | Selected adult/larval sparse matrices and metadata; data preparation only |

- Закреплённый GitHub LFS-маршрут `plastic_weights.pt` claude-fly дважды вернул HTTP404. Это блокировка этого маршрута; доступность иных архивов не проверена. Подмены весов нет.
- Бинарный экспорт snedea получен по закреплённому первичному URL: 12443952 байта; SHA256 `fbf8d440ca1207c7573e1acdd2366f9d0beb9b533c1710f21681264f81b1cc49`. Биологическая идентичность исходного материала не доказывается одним хешем экспорта.
- Получен манифест внешнего экспорта FLYBOX. Получение манифеста не означает загрузку всех частей и выполнение полного сценария.
- У полученного snedea-экспорта проверены SHA256, gzip, размеры, конечность весов, диапазоны и сортировка индексов, полнота метаданных. Исходные FlyWire/root-ID не содержатся в этом бинарном формате; для биологического происхождения нужно отдельное отображение. JSON манифеста FLYBOX и его SHA256 проверены без запуска модели.
- В исходнике snedea `reset` не обнуляет счётчик времени. Подготовленная проверка экспортирует это ограничение и завершается с ошибкой при неполном сбросе. Исполнение этой проверки ещё не проводилось.
- FlyGym2.1.0 и Gymnasium1.3.2 имеют разные интерфейсы и зависимости. Старые `from flygym import Fly` не становятся совместимыми от установки переименованного пакета.
- Sparse-ветка snnTorch на закреплённом commit доступна в коде. Оценка 60ГБ относится к dense-варианту и не служит основанием исключить sparse-проверку.
- Разные materialisations, фильтры рёбер, знаки, задержки и нормы весов дают разные модели. Сравнение скорости не доказывает эквивалентность результатов.
- Тело, игровая сцена, сокращённая сеть, полный зарегистрированный граф и подготовка данных учитываются отдельными сценариями. Авторские оценки скорости не представлены как наши измерения.
- Вариант GPL, область лицензии данных и право распространения производных требуют отдельной проверки; отсутствие LICENSE не является разрешением на переиспользование.

## Условия продолжения

Образы и зависимости CPU-профилей ещё не приняты по результатам установки: команды используют upstream-требования, а разрешённые зависимости сохраняются в `dependencies.lock.txt` каждого будущего прогона. Команды не означают готовую проверенную среду. Браузерные проверки, численные сравнения и измерение стоимости экспорта также остаются открытыми.

После освобождения памяти сначала выполнить небольшие CPU-сценарии SOUP и snedea, затем FlyGym и body-demo Fly Arena. Полные сети, обучение, Julia/R/MATLAB и GPU требуют своих сред и входов. У каждого прогона сохраняются команда, профиль, commit, причины остановки и хеш лога в `research/.work/simulator-evaluation/<ID>/<run>/`.

Установка ограничена 30 минутами, smoke — 10, функциональная проверка — 30. Одновременно допускается один вычислительный сценарий, до четырёх CPU-потоков, до 4ГБ RAM; сохраняются 2ГБ свободной памяти системы. Текущие профили CPU отключают GPU. GPU-проверки и измерение VRAM остаются невыполненными.

Технические требования и три условных варианта продолжения: [generator-requirements.md](generator-requirements.md). Открытые проверки: [TODO.md](TODO.md).

## Итоги запусков и варианты использования

Для каждого испытанного репозитория: проверенный сценарий и статус, доказательства, исправленные проблемы, плюсы, минусы и три варианта использования. Успешный запуск не означает биологическую валидацию; решение об архитектуре принимается после сравнения кандидатов.

### SIM-001 — artem-x-meta/fly-arena

Fly Arena успешно запускается: body-demo seeds 1/2/3 и повтор seed 1; полный MaleCNS 166700 нейронов / 25582938 связей прошёл короткий запуск 0,1 с без ошибок. В проверенных сценариях нерешённых блокеров запуска нет.

**Проверено:** 7 штатных тестов, CLI, тело, подготовка графа, короткий headless запуск полной сети, CSV/JSON/MP4 и сохранение нейронного состояния.

**Плюсы:** Уже объединены физическое тело, среда, полный MaleCNS и управляемая нейродинамика; CLI, seeds, телеметрия, видео и нейронные checkpoints облегчают автоматизацию; CPU достаточен для проверенного сценария; публичные данные с SHA-256; код MIT, коннектом CC BY 4.0.

**Минусы и границы:** Упрощённая LIF-модель, условные знаки медиаторов и управляемый CPG не подтверждают естественное поведение; 0,1 с модели требуют около 3,6 с цикла на нашей машине; интерактивная скорость не подтверждена; Долгие сценарии, повторяемость полной сети, абляции и полное восстановление арены не проверены; Человеческого физического оператора ECAP нет.

**Исправлено:** Mesa/EGL для headless Linux; pytest capture=sys на Windows bind mount; Закрытие writable mmap перед SHA-256 в рабочей копии; Резерв RAM снят по разрешению пользователя для полного испытания; лимит контейнера 4 ГиБ сохранён.

**Измеренная пиковая RAM контейнера:** {'prepare': 2564194304, 'connectome': 1263214592} байт.

- **Доработать:** Сильный кандидат для быстрого прототипа среды Drosophila. Потребуются устойчивый API шаг/reset/наблюдение/стимуляция, длительные проверки и научная калибровка.
- **Объединить сервисами:** Кандидат на отдельный сервис тела/среды; нейронный backend и человеческий ECAP-оператор можно отделить. Нужно согласовать граф, единицы, шаг времени, состояние и задержки; совместимость ещё не проверена.
- **Разработать с нуля:** Использовать подготовку разреженного графа, порты и экспорт как технические образцы. Собственная реализация даст контроль, но потребует заново проверять физику, динамику и воспроизводимость.

**Предварительное решение:** Сохранить как работоспособного кандидата для адаптации и композиции; окончательный выбор после сопоставимых испытаний остальных репозиториев.

**Квитанции:** `research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/body-export-audit.json`; `research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/full-connectome-trial.json`; `research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/full-connectome-export-audit.json`

### SIM-002 — chaobrain/fitting_drosophila_whole_brain_spiking_model

SIM-002 установлен; pip check, CLI и загрузка реальных классов модели прошли после добавления brainscale==0.1.0. Полный расчёт не воспроизведён: конструктор Population останавливается на отсутствии data/Completeness_630_final.csv. Это частичная проверка, а не успешно работающий полный симулятор.

**Проверено:** CPU Docker, Python 3.12; установка исходных requirements, отдельно исправление зависимости, импорт Population/load_syn, реальный вызов конструктора. Штатные тесты отсутствуют; обучение, прогноз, seeds и экспорт динамики не проверены.

**Плюсы:** Коннектомно-ограниченная LIF-модель, разреженный CSR и низкоранговая адаптация пригодны для изучения обучаемого представления; Двухэтапная схема SNN и RNN, генерация промежуточных данных и оценка предсказания активности; Явный выбор FlyWire v630/v783; код описывает работу с областями мозга и нейронной активностью.

**Минусы и границы:** Нет физического тела, среды, взаимодействия с объектами и человеческого ECAP-оператора; Авторские CSV/parquet/NPZ отсутствуют в checkout; Google Drive отдаёт страницу подтверждения проверки большого файла, архив не скачан и его содержимое не проверено. Это не доказательство недоступности данных; Версии исходных requirements не закреплены, потребовалась дополнительная зависимость; сохранены исходный и исправленный lock-файлы; Лицензия всего репозитория не установлена: два Python-файла содержат Apache-2.0 headers, отдельного LICENSE нет; Скорость и память полного расчёта, обучение и воспроизводимость не измерены; вывод кальциевой активности в спайковые частоты требует проверки допущений.

**Исправлено:** BrainX из исходных requirements не содержит импортируемый brainscale; установка brainscale==0.1.0 исправила импорт; изменён только профиль окружения; Резерв RAM отключён по указанию пользователя для испытания, лимит контейнера 4 ГиБ сохранён.

**Измеренная пиковая RAM контейнера:** {'repair': 50454528, 'model_probe': 473313280} байт.

- **Доработать:** Рассматривать для подгонки нейродинамики и обучения представления, но не как готовую embodied-среду. До адаптации получить и проверить точные авторские данные, права и воспроизводимость вычислений.
- **Объединить сервисами:** Возможный отдельный модуль обучения нейронной динамики рядом с сервисом тела. Нужно согласовать графы, популяции, наблюдаемые величины и время; FlyWire v630/v783 нельзя незаметно заменить MaleCNS.
- **Разработать с нуля:** Полезны разреженная связность, LoRA и двухэтапная подгонка. Свой модуль может дать строгий контракт данных и тестируемый reset; корректность метода и перенос в ECAP ещё предстоит доказать.

**Предварительное решение:** Сохранить как методического кандидата на обучение представления. Не выбирать основным симулятором до получения данных и функционального воспроизведения.

**Квитанции:** `research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/result.json`; `research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/dependency-repair.json`; `research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/data-probe-result.json`; `research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/data-prerequisite.json`; `research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/author-data-access.json`

### SIM-003 — cnqso/infinite-sugar

SIM-003 Infinite Sugar успешно собирается и запускается в настоящем Edge с программным WebGL: 139255 нейронов / 2700513 связей. npm test и typecheck прошли; проверены старт, продвижение времени сети/физики, пауза, включение/выключение сахара, центрирование камеры и инспектор. В проверенных сценариях нерешённых блокеров запуска нет.

**Проверено:** Закреплённые Git blobs, Node 22.19.0, штатные проверки нейронной карты и MuJoCo WASM, headless Edge 1280x800. Состояния нейронов и физики конечны; ошибок страницы и загрузки ресурсов нет. Профиль браузера, скриншоты и квитанции сохранены в .work.

**Плюсы:** Настоящий интерактивный браузерный запуск без Python/CUDA и нейронный граф в поставляемых файлах; Проверенные тесты используют реальный граф и MuJoCo WASM, включая сахарный отклик, молчание, устойчивость тела и сброс часов; Есть раздельные brain/controller/physics компоненты, отображение активности и программный доступ к состояниям.

**Минусы и границы:** Весовые коэффициенты подобраны вручную; движения крыльев и часть движений лап задаются шаблонами, сцена не является полноценным сенсорным миром; 139255/2700513 — поставляемый обработанный граф FlyWire, он не эквивалентен MaleCNS Fly Arena; фильтры и исходную lineage нужно сравнивать отдельно; Лицензия кода не установлена; README относит данные FlyWire к CC BY-NC 4.0, права на все компоненты требуют проверки; Сброс тела сохраняет состояние мозга; интерфейс seeds и потокового экспорта для датасета нужно доработать; Длительные browser-сценарии, три независимых seeds, интерактивная скорость на GPU и биологическая достоверность не проверены; ECAP-оператора нет.

**Исправлено:** Sparse checkout исключал manifest, граф и модели тела; точные blobs закреплённого коммита восстановлены только в рабочей копии. Восстановление включено в simctl; В браузерной проверке учтён автоматически открываемый About; это исправление тестового сценария, исходный интерфейс не менялся; Резерв RAM отключён по разрешению пользователя; контейнерные этапы ограничены 4 ГиБ. Браузер проверен отдельным коротким host-сценарием, его пик RAM отдельно не измерялся.

**Измеренная пиковая RAM контейнера:** {'install': 184741888, 'native_tests': 684908544, 'smoke': 122626048} байт.

- **Доработать:** Хороший кандидат для интерактивной демонстрации и быстрой проверки стимул/нейродинамика/тело. Для генератора потребуются права, headless API, единый reset, seeds, экспорт единиц и состояния.
- **Объединить сервисами:** Можно использовать как браузерный клиент и отдельный WASM-компонент, сохранив вычислительный backend отдельно. Нужны контракт наблюдений, синхронизация времени и проверка эквивалентности графов.
- **Разработать с нуля:** Полезны эффективный JS LIF-kernel, разреженная задержанная ингибиция, привязка портов и тесты. Заимствование кода возможно после установления лицензии; своё ядро надо валидировать заново.

**Предварительное решение:** Сохранить как работоспособного кандидата для демонстрации/фронтенда и методический образец. Для основного генератора сравнить научный контроль, экспорт и лицензии с другими проектами.

**Квитанции:** `research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/result.json`; `research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/pinned-assets.json`; `research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-result.json`; `research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-scene.png`; `research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-inspector.png`

### SIM-004 — cooneypc4/larval_escape_manuscript

SIM-004 larval_escape_manuscript — авторский анализ поведения личинок и SCAPE-съёмки мышц, не симулятор. Проверены закреплённые исходники и синтаксис Python; MATLAB/Octave не найдены в PATH и стандартных каталогах. Вычислительное воспроизведение заблокировано отсутствием среды и исходных данных.

**Проверено:** Проверка чистого pinned checkout, рабочая копия, статический инвентарь MATLAB/Python, точные входные файлы и GUI-зависимости. MATLAB, Python-анализ данных и экспериментальные результаты не исполнялись.

**Плюсы:** Методы сопоставления мышечных флуоресцентных сигналов с движением, ROI, тепловые карты и анализ PMN/MN связности; Первичный авторский код связан с зарегистрированной работой S864; полезен как материал для протокола экспериментальной проверки наблюдаемых величин.

**Минусы и границы:** Нет тела/среды симуляции, нейронного solver, стимуляции, генератора данных или ECAP-оператора; Нет двух необходимых XLSX, исходных SCAPE MAT/TIFF и Track_gui_PC.fig; README не содержит маршрута получения данных и требований окружения; GUI/ручной выбор ROI, персональные абсолютные пути и незакреплённые зависимости препятствуют пакетному воспроизведению; Лицензия переиспользования кода не установлена; личинка и мышечная кальциевая активность не эквивалентны взрослому коннектому и спайковым состояниям.

**Исправлено:** Демо-сервер SIM-003 остановлен; исходные sidecars не изменены; Установлено фактическое назначение: анализ экспериментальных измерений личинки, а не генерация синтетических нейронных состояний.

**Измеренная пиковая RAM контейнера:** {} байт.

- **Доработать:** Низкий приоритет для самого генератора. Может пригодиться для анализа реальных наблюдений после получения данных, MATLAB-среды и устранения ручных путей/GUI.
- **Объединить сервисами:** Рассматривать только как отдельную офлайн-процедуру анализа/валидации, а не сервис симуляции. Сначала определить входные схемы, единицы и автоматизацию ROI.
- **Разработать с нуля:** Использовать идеи обработки ROI, сопоставления поведения и сигналов, shuffle-сравнений. Переписать нужный анализ с явными контрактами; перенос кода требует разрешённой лицензии.

**Предварительное решение:** Не считать кандидатом ядра генератора. Сохранить как методический материал валидации личиночных/мышечных измерений; не подменять отсутствие данных успешным запуском.

**Квитанции:** `research/.work/simulator-evaluation/SIM-004/20261005T123456Z-preflight/preflight.json`

### SIM-005 — emebeiran/connconstr

Установка и pip check, функциональная проверка RNN, авторская модель Figure 1 (300 нейронов) прошли. Авторский сценарий Figure 5 на hemibrain: passed.

**Проверено:** Программная проверка, авторские синтетические веса и модель центрального комплекса из hemibrain. Не модель всего мозга, тела или человеческого ECAP; не воспроизведение всех результатов статьи.

**Плюсы:** Авторский код обучения connectome-constrained RNN и доступные данные для Figure 1–5.; Доступ к весам, нейронным состояниям, loss и экспорту NumPy/PyTorch.; Короткие seeded проверки и восстановление состояния воспроизводимы на CPU..

**Минусы и границы:** Нет тела, среды и физического оператора ECAP.; Исследовательские монолитные скрипты без штатного тестового пакета; зависимости требуют явного закрепления.; Плотная матрица полного hemibrain загружается перед выделением небольшой подсети.; Лицензия архива Zenodo CC BY 4.0 не устанавливает автоматически лицензию всего Git-репозитория.; Полный авторский сценарий не имеет внешнего задания seed; его повторяемость отдельно не подтверждена..

**Исправлено:** Добавлена pandas для авторского сценария; подготовлен каталог Figs и безоконный backend Agg.; Архив Zenodo 16618353 скачан и проверен по MD5 и SHA-256.; По решению пользователя сняты ограничение RAM Docker и проверка запаса RAM; сценарий действительно запущен..

**Измеренная пиковая RAM контейнера:** {'author_figure5_peak_bytes': 4769677312} байт.

- **Доработать:** Выделить RNN, обучение и загрузчик подсети в отдельный модуль; заменить плотную подготовку графа при необходимости и закрепить единицы/seed/экспорт.
- **Объединить сервисами:** Использовать отдельный компонент обучения представлений рядом с embodied-симулятором и независимым человеческим ECAP-оператором.
- **Разработать с нуля:** Использовать как методический ориентир и контрольную реализацию; права на перенос кода проверить отдельно.

**Предварительное решение:** Сохранить как методический кандидат обучения и проверки переносимых представлений. Архитектуру генератора выбирать после испытаний остальных репозиториев.

**Квитанции:** `research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/result.json`; `research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/author-archive.json`; `research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/extracted-author-data.json`; `research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/author_dependencies-result.json`; `research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/author_run-result.json`; `research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/exports/connconstr-fixture/result.json`; `research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/exports/connconstr-author-teacher/result.json`
