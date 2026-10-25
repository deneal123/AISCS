# Отчёт об испытаниях репозиториев

Текущий срез испытаний; даты, команды, версии и измерения сохранены в квитанциях. Установка, программная проверка, функциональное воспроизведение и биологическая достоверность учитываются отдельно.

[Проверки](TODO.md) · [Визуальные результаты](artifacts/README.md) · [Порядок работы](docs/WORKFLOW.md) · [Реестр](data/registry.json) · [Профили запуска](data/profiles.json)

## Сводка

Подключено 32 репозитория. Разбор результатов зарегистрирован для 9; визуальные материалы опубликованы для 5. Наличие исполняемого профиля не означает завершённого испытания.

Сохраняются **35/43, G0_REVISE, saturation=false**, 15 неранжированных вариантов. Архитектура генератора не выбрана. Нейродинамика Drosophila, тело и среда, перенос представлений и человеческий оператор ECAP — отдельные компоненты. Запуск не подтверждает клиническую эффективность.

| SIM | Репозиторий | Назначение | Текущий результат |
|---|---|---|---|
| [SIM-001](#sim-001) | artem-x-meta/fly-arena | embodied | passed_tested_scenarios |
| [SIM-002](#sim-002) | chaobrain/fitting_drosophila_whole_brain_spiking_model | neural-fitting | partial_missing_data |
| [SIM-003](#sim-003) | cnqso/infinite-sugar | neural | passed_tested_scenarios |
| [SIM-004](#sim-004) | cooneypc4/larval_escape_manuscript | author-analysis | blocked_missing_runtime_and_data |
| [SIM-005](#sim-005) | emebeiran/connconstr | method-comparator | passed_tested_scenarios |
| [SIM-006](#sim-006) | eonsystemspbc/fly-brain | neural | passed_tested_scenarios_with_limitations |
| [SIM-007](#sim-007) | erankopel/maleCNS-depth | connectome-preparation | passed_tested_scenarios_with_limitations |
| [SIM-008](#sim-008) | flyconnectome/2025malecns | connectome-preparation | partial_full_notebook_blocked_by_observed_global_oom |
| [SIM-009](#sim-009) | gauravvvvvvvvvv/flybox | browser-neural | passed_tested_scenarios |
| [SIM-010](#sim-010) | hsseung/OpticLobe.jl | connectome-preparation | итоговый разбор не завершён |
| [SIM-011](#sim-011) | htem/BANC-project | connectome-preparation | итоговый разбор не завершён |
| [SIM-012](#sim-012) | htem/FANC_auto_recon | connectome-preparation | итоговый разбор не завершён |
| [SIM-013](#sim-013) | jajmcallister/Conn_ESN_Paper | method-comparator | итоговый разбор не завершён |
| [SIM-014](#sim-014) | JNLiew/flylif_orientation_maps | neural | итоговый разбор не завершён |
| [SIM-015](#sim-015) | legacyindiesubmissions-ai/claude-fly | embodied | итоговый разбор не завершён |
| [SIM-016](#sim-016) | MakazhanAlpamys/soup-connectome | neural | итоговый разбор не завершён |
| [SIM-017](#sim-017) | murthylab/flywire-network-analysis | connectome-preparation | итоговый разбор не завершён |
| [SIM-018](#sim-018) | nalin-dhiman/Connectome-Constrained-Neural-Networks | neural | итоговый разбор не завершён |
| [SIM-019](#sim-019) | nalin-dhiman/ScaleBreak-FlyVis | method-comparator | итоговый разбор не завершён |
| [SIM-020](#sim-020) | NeLy-EPFL/flygym | body-environment | итоговый разбор не завершён |
| [SIM-021](#sim-021) | NeLy-EPFL/flygym-gymnasium | body-environment-compatibility | итоговый разбор не завершён |
| [SIM-022](#sim-022) | Neuromorphicism/fly-brain-snntorch | neural | итоговый разбор не завершён |
| [SIM-023](#sim-023) | nftechie/doomfly | embodied-game | итоговый разбор не завершён |
| [SIM-024](#sim-024) | philshiu/Drosophila_brain_model | neural | итоговый разбор не завершён |
| [SIM-025](#sim-025) | rdarie/modular-bionic-interface-2026 | human-neural-interface-comparator | итоговый разбор не завершён |
| [SIM-026](#sim-026) | seung-lab/FlyConnectome | connectome-preparation | итоговый разбор не завершён |
| [SIM-027](#sim-027) | smpuglie/Pugliese_2026 | motor-cpg | итоговый разбор не завершён |
| [SIM-029](#sim-029) | snedea/flybrain | browser-neural | итоговый разбор не завершён |
| [SIM-030](#sim-030) | Stavros963/fcta | connectome-analysis | итоговый разбор не завершён |
| [SIM-031](#sim-031) | TuragaLab/flyvis | visual-neural | итоговый разбор не завершён |
| [SIM-032](#sim-032) | TuragaLab/wormvae | other-organism-comparator | итоговый разбор не завершён |
| [SIM-033](#sim-033) | YijieYin/connectome_data_prep | connectome-preparation | итоговый разбор не завершён |

## Происхождение и общие ограничения

- Поколение оснований: `g-56b4c46e48ad7a8b5db92c99`; исходный срез: `2026-10-04`.
- Переименования сохранены в `repository_aliases` реестра; дубли не подключаются.
- Лицензии кода, данных и право распространения производных проверяются раздельно. Отсутствие LICENSE не означает разрешение на использование.
- Различия materialisation, фильтров, знаков, задержек и нормировки весов меняют модель. Сравнение скорости не подтверждает эквивалентность.
- Исторические прогоны с резервом RAM остаются в квитанциях. Текущая политика: без лимита RAM и резерва; до четырёх CPU-потоков, один вычислительный запуск одновременно. GPU проверяется отдельно.
- Последняя уборка: [cleanup-20261025T141017Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T141017Z.json>); удалено 0.00 ГиБ временных файлов по логическому размеру. Квитанции, численные экспорты и визуальные материалы сохранены.
- Проверка защищённых файлов: [current-integrity.json](<../research/.work/simulator-evaluation/SIM-006/evaluation-input-20261025/current-integrity.json>). Исторический baseline сохранён, его хеши не подменяются.

<a id="итоги-запусков-и-варианты-использования"></a>
## Результаты по SIM

<a id="sim-001"></a>
### SIM-001 — artem-x-meta/fly-arena

**Исходники:** [12f48c702ed170b5bdc4643afa7ce65e952b353d](https://github.com/artem-x-meta/fly-arena/tree/12f48c702ed170b5bdc4643afa7ce65e952b353d); связанные ресурсы: ST011.

**Данные и версия:** MaleCNS; body-demo does not load the graph

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-001/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-001/source-inventory.json>); [источник](https://github.com/artem-x-meta/fly-arena/tree/12f48c702ed170b5bdc4643afa7ce65e952b353d) |
| Установить окружение и проверить зависимости | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/result.json>) |
| Выполнить штатные или явно обозначенные программные проверки | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/result.json>) |
| Проверить минимальный запуск или CLI | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/result.json>) |
| Выполнить функциональный сценарий с согласованными данными | выполнено | [body-export-audit.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/body-export-audit.json>); [full-connectome-trial.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/full-connectome-trial.json>); [full-connectome-export-audit.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/full-connectome-export-audit.json>) |
| Проверить повторяемость короткого сценария и seeds, где применимо | выполнено | [body-export-audit.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/body-export-audit.json>) |
| Сохранить проверенные визуальные материалы | выполнено | [full-connectome-seed1.mp4](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/exports/full-connectome-seed1.mp4>) |
| Записать итог, ограничения и три варианта применения | выполнено | [body-export-audit.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/body-export-audit.json>); [full-connectome-trial.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/full-connectome-trial.json>); [full-connectome-export-audit.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/full-connectome-export-audit.json>) |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

**Итог (2026-10-05):** Fly Arena успешно запускается: body-demo seeds 1/2/3 и повтор seed 1; полный MaleCNS 166700 нейронов / 25582938 связей прошёл короткий запуск 0,1 с без ошибок. В проверенных сценариях нерешённых блокеров запуска нет.

**Область проверки:** 7 штатных тестов, CLI, тело, подготовка графа, короткий headless запуск полной сети, CSV/JSON/MP4 и сохранение нейронного состояния.

**Измеренная пиковая RAM, байт:** `{"prepare": 2564194304, "connectome": 1263214592}`.

**Существенные исправления:**

- Mesa/EGL для headless Linux
- pytest capture=sys на Windows bind mount
- Закрытие writable mmap перед SHA-256 в рабочей копии
- Резерв RAM снят по разрешению пользователя для полного испытания; лимит контейнера 4 ГиБ сохранён

**Преимущества:**

- Уже объединены физическое тело, среда, полный MaleCNS и управляемая нейродинамика
- CLI, seeds, телеметрия, видео и нейронные checkpoints облегчают автоматизацию
- CPU достаточен для проверенного сценария; публичные данные с SHA-256; код MIT, коннектом CC BY 4.0

**Ограничения:**

- Упрощённая LIF-модель, условные знаки медиаторов и управляемый CPG не подтверждают естественное поведение
- 0,1 с модели требуют около 3,6 с цикла на нашей машине; интерактивная скорость не подтверждена
- Долгие сценарии, повторяемость полной сети, абляции и полное восстановление арены не проверены
- Человеческого физического оператора ECAP нет

| Продолжение | Оценка |
|---|---|
| Адаптация | Сильный кандидат для быстрого прототипа среды Drosophila. Потребуются устойчивый API шаг/reset/наблюдение/стимуляция, длительные проверки и научная калибровка. |
| Композиция сервисов | Кандидат на отдельный сервис тела/среды; нейронный backend и человеческий ECAP-оператор можно отделить. Нужно согласовать граф, единицы, шаг времени, состояние и задержки; совместимость ещё не проверена. |
| Собственная реализация | Использовать подготовку разреженного графа, порты и экспорт как технические образцы. Собственная реализация даст контроль, но потребует заново проверять физику, динамику и воспроизводимость. |

**Предварительное решение:** Сохранить как работоспособного кандидата для адаптации и композиции; окончательный выбор после сопоставимых испытаний остальных репозиториев.

**Квитанции:** [body-export-audit.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/body-export-audit.json>); [full-connectome-trial.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/full-connectome-trial.json>); [full-connectome-export-audit.json](<../research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc/full-connectome-export-audit.json>).

[Визуальные материалы SIM-001](artifacts/SIM-001/README.md).

<a id="sim-002"></a>
### SIM-002 — chaobrain/fitting_drosophila_whole_brain_spiking_model

**Исходники:** [f1389ba8b0e7c9f4059d2538b6b799c3e88342ee](https://github.com/chaobrain/fitting_drosophila_whole_brain_spiking_model/tree/f1389ba8b0e7c9f4059d2538b6b799c3e88342ee); связанные ресурсы: ST013.

**Данные и версия:** FlyWire v630/v783 and figshare activity; author preprocessed files required

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-002/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-002/source-inventory.json>); [источник](https://github.com/chaobrain/fitting_drosophila_whole_brain_spiking_model/tree/f1389ba8b0e7c9f4059d2538b6b799c3e88342ee) |
| Установить окружение и проверить зависимости | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/result.json>) |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | выполнено | [dependency-repair.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/dependency-repair.json>) |
| Выполнить функциональный сценарий с согласованными данными | блокировано | [result.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/result.json>); [dependency-repair.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/dependency-repair.json>); [data-probe-result.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/data-probe-result.json>); [data-prerequisite.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/data-prerequisite.json>); [author-data-access.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/author-data-access.json>) |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/result.json>); [dependency-repair.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/dependency-repair.json>); [data-probe-result.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/data-probe-result.json>); [data-prerequisite.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/data-prerequisite.json>); [author-data-access.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/author-data-access.json>) |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

**Итог (2026-10-05):** SIM-002 установлен; pip check, CLI и загрузка реальных классов модели прошли после добавления brainscale==0.1.0. Полный расчёт не воспроизведён: конструктор Population останавливается на отсутствии data/Completeness_630_final.csv. Это частичная проверка, а не успешно работающий полный симулятор.

**Область проверки:** CPU Docker, Python 3.12; установка исходных requirements, отдельно исправление зависимости, импорт Population/load_syn, реальный вызов конструктора. Штатные тесты отсутствуют; обучение, прогноз, seeds и экспорт динамики не проверены.

**Измеренная пиковая RAM, байт:** `{"repair": 50454528, "model_probe": 473313280}`.

**Существенные исправления:**

- BrainX из исходных requirements не содержит импортируемый brainscale; установка brainscale==0.1.0 исправила импорт; изменён только профиль окружения
- Резерв RAM отключён по указанию пользователя для испытания, лимит контейнера 4 ГиБ сохранён

**Преимущества:**

- Коннектомно-ограниченная LIF-модель, разреженный CSR и низкоранговая адаптация пригодны для изучения обучаемого представления
- Двухэтапная схема SNN и RNN, генерация промежуточных данных и оценка предсказания активности
- Явный выбор FlyWire v630/v783; код описывает работу с областями мозга и нейронной активностью

**Ограничения:**

- Нет физического тела, среды, взаимодействия с объектами и человеческого ECAP-оператора
- Авторские CSV/parquet/NPZ отсутствуют в checkout; Google Drive отдаёт страницу подтверждения проверки большого файла, архив не скачан и его содержимое не проверено. Это не доказательство недоступности данных
- Версии исходных requirements не закреплены, потребовалась дополнительная зависимость; сохранены исходный и исправленный lock-файлы
- Лицензия всего репозитория не установлена: два Python-файла содержат Apache-2.0 headers, отдельного LICENSE нет
- Скорость и память полного расчёта, обучение и воспроизводимость не измерены; вывод кальциевой активности в спайковые частоты требует проверки допущений

| Продолжение | Оценка |
|---|---|
| Адаптация | Рассматривать для подгонки нейродинамики и обучения представления, но не как готовую embodied-среду. До адаптации получить и проверить точные авторские данные, права и воспроизводимость вычислений. |
| Композиция сервисов | Возможный отдельный модуль обучения нейронной динамики рядом с сервисом тела. Нужно согласовать графы, популяции, наблюдаемые величины и время; FlyWire v630/v783 нельзя незаметно заменить MaleCNS. |
| Собственная реализация | Полезны разреженная связность, LoRA и двухэтапная подгонка. Свой модуль может дать строгий контракт данных и тестируемый reset; корректность метода и перенос в ECAP ещё предстоит доказать. |

**Предварительное решение:** Сохранить как методического кандидата на обучение представления. Не выбирать основным симулятором до получения данных и функционального воспроизведения.

**Квитанции:** [result.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/result.json>); [dependency-repair.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/dependency-repair.json>); [data-probe-result.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/data-probe-result.json>); [data-prerequisite.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/data-prerequisite.json>); [author-data-access.json](<../research/.work/simulator-evaluation/SIM-002/20261005T115256Z-de6935/author-data-access.json>).

[Визуальные материалы SIM-002](artifacts/SIM-002/README.md).

<a id="sim-003"></a>
### SIM-003 — cnqso/infinite-sugar

**Исходники:** [fdbbd866b203a709a164970b0a8996108edd57a5](https://github.com/cnqso/infinite-sugar/tree/fdbbd866b203a709a164970b0a8996108edd57a5); связанные ресурсы: canonical-source, S201.

**Данные и версия:** Author FlyWire export; supplied motor patterns coexist with neural readouts

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-003/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-003/source-inventory.json>); [источник](https://github.com/cnqso/infinite-sugar/tree/fdbbd866b203a709a164970b0a8996108edd57a5) |
| Установить окружение и проверить зависимости | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/result.json>) |
| Выполнить штатные или явно обозначенные программные проверки | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/result.json>) |
| Проверить минимальный запуск или CLI | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/result.json>) |
| Выполнить функциональный сценарий с согласованными данными | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/result.json>); [pinned-assets.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/pinned-assets.json>); [browser-result.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-result.json>); [browser-scene.png](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-scene.png>); [browser-inspector.png](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-inspector.png>) |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | выполнено | [browser-scene.png](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-scene.png>); [browser-inspector.png](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-inspector.png>) |
| Записать итог, ограничения и три варианта применения | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/result.json>); [pinned-assets.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/pinned-assets.json>); [browser-result.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-result.json>); [browser-scene.png](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-scene.png>); [browser-inspector.png](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-inspector.png>) |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

**Итог (2026-10-05):** SIM-003 Infinite Sugar успешно собирается и запускается в настоящем Edge с программным WebGL: 139255 нейронов / 2700513 связей. npm test и typecheck прошли; проверены старт, продвижение времени сети/физики, пауза, включение/выключение сахара, центрирование камеры и инспектор. В проверенных сценариях нерешённых блокеров запуска нет.

**Область проверки:** Закреплённые Git blobs, Node 22.19.0, штатные проверки нейронной карты и MuJoCo WASM, headless Edge 1280x800. Состояния нейронов и физики конечны; ошибок страницы и загрузки ресурсов нет. Профиль браузера, скриншоты и квитанции сохранены в .work.

**Измеренная пиковая RAM, байт:** `{"install": 184741888, "native_tests": 684908544, "smoke": 122626048}`.

**Существенные исправления:**

- Sparse checkout исключал manifest, граф и модели тела; точные blobs закреплённого коммита восстановлены только в рабочей копии. Восстановление включено в simctl
- В браузерной проверке учтён автоматически открываемый About; это исправление тестового сценария, исходный интерфейс не менялся
- Резерв RAM отключён по разрешению пользователя; контейнерные этапы ограничены 4 ГиБ. Браузер проверен отдельным коротким host-сценарием, его пик RAM отдельно не измерялся

**Преимущества:**

- Настоящий интерактивный браузерный запуск без Python/CUDA и нейронный граф в поставляемых файлах
- Проверенные тесты используют реальный граф и MuJoCo WASM, включая сахарный отклик, молчание, устойчивость тела и сброс часов
- Есть раздельные brain/controller/physics компоненты, отображение активности и программный доступ к состояниям

**Ограничения:**

- Весовые коэффициенты подобраны вручную; движения крыльев и часть движений лап задаются шаблонами, сцена не является полноценным сенсорным миром
- 139255/2700513 — поставляемый обработанный граф FlyWire, он не эквивалентен MaleCNS Fly Arena; фильтры и исходную lineage нужно сравнивать отдельно
- Лицензия кода не установлена; README относит данные FlyWire к CC BY-NC 4.0, права на все компоненты требуют проверки
- Сброс тела сохраняет состояние мозга; интерфейс seeds и потокового экспорта для датасета нужно доработать
- Длительные browser-сценарии, три независимых seeds, интерактивная скорость на GPU и биологическая достоверность не проверены; ECAP-оператора нет

| Продолжение | Оценка |
|---|---|
| Адаптация | Хороший кандидат для интерактивной демонстрации и быстрой проверки стимул/нейродинамика/тело. Для генератора потребуются права, headless API, единый reset, seeds, экспорт единиц и состояния. |
| Композиция сервисов | Можно использовать как браузерный клиент и отдельный WASM-компонент, сохранив вычислительный backend отдельно. Нужны контракт наблюдений, синхронизация времени и проверка эквивалентности графов. |
| Собственная реализация | Полезны эффективный JS LIF-kernel, разреженная задержанная ингибиция, привязка портов и тесты. Заимствование кода возможно после установления лицензии; своё ядро надо валидировать заново. |

**Предварительное решение:** Сохранить как работоспособного кандидата для демонстрации/фронтенда и методический образец. Для основного генератора сравнить научный контроль, экспорт и лицензии с другими проектами.

**Квитанции:** [result.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/result.json>); [pinned-assets.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/pinned-assets.json>); [browser-result.json](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-result.json>); [browser-scene.png](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-scene.png>); [browser-inspector.png](<../research/.work/simulator-evaluation/SIM-003/20261005T121548Z-529787/browser-inspector.png>).

[Визуальные материалы SIM-003](artifacts/SIM-003/README.md).

<a id="sim-004"></a>
### SIM-004 — cooneypc4/larval_escape_manuscript

**Исходники:** [c927d42b7234add7df3ead576a8effc02facce18](https://github.com/cooneypc4/larval_escape_manuscript/tree/c927d42b7234add7df3ead576a8effc02facce18); связанные ресурсы: canonical-source, S864.

**Данные и версия:** Larval escape behaviour and SCAPE muscle recordings; analysis only

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-004/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-004/source-inventory.json>); [источник](https://github.com/cooneypc4/larval_escape_manuscript/tree/c927d42b7234add7df3ead576a8effc02facce18) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | блокировано | [preflight.json](<../research/.work/simulator-evaluation/SIM-004/20261005T123456Z-preflight/preflight.json>) |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | выполнено | [preflight.json](<../research/.work/simulator-evaluation/SIM-004/20261005T123456Z-preflight/preflight.json>) |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

**Итог (2026-10-05):** SIM-004 larval_escape_manuscript — авторский анализ поведения личинок и SCAPE-съёмки мышц, не симулятор. Проверены закреплённые исходники и синтаксис Python; MATLAB/Octave не найдены в PATH и стандартных каталогах. Вычислительное воспроизведение заблокировано отсутствием среды и исходных данных.

**Область проверки:** Проверка чистого pinned checkout, рабочая копия, статический инвентарь MATLAB/Python, точные входные файлы и GUI-зависимости. MATLAB, Python-анализ данных и экспериментальные результаты не исполнялись.

**Измеренная пиковая RAM, байт:** `{}`.

**Существенные исправления:**

- Демо-сервер SIM-003 остановлен; исходные sidecars не изменены
- Установлено фактическое назначение: анализ экспериментальных измерений личинки, а не генерация синтетических нейронных состояний

**Преимущества:**

- Методы сопоставления мышечных флуоресцентных сигналов с движением, ROI, тепловые карты и анализ PMN/MN связности
- Первичный авторский код связан с зарегистрированной работой S864; полезен как материал для протокола экспериментальной проверки наблюдаемых величин

**Ограничения:**

- Нет тела/среды симуляции, нейронного solver, стимуляции, генератора данных или ECAP-оператора
- Нет двух необходимых XLSX, исходных SCAPE MAT/TIFF и Track_gui_PC.fig; README не содержит маршрута получения данных и требований окружения
- GUI/ручной выбор ROI, персональные абсолютные пути и незакреплённые зависимости препятствуют пакетному воспроизведению
- Лицензия переиспользования кода не установлена; личинка и мышечная кальциевая активность не эквивалентны взрослому коннектому и спайковым состояниям

| Продолжение | Оценка |
|---|---|
| Адаптация | Низкий приоритет для самого генератора. Может пригодиться для анализа реальных наблюдений после получения данных, MATLAB-среды и устранения ручных путей/GUI. |
| Композиция сервисов | Рассматривать только как отдельную офлайн-процедуру анализа/валидации, а не сервис симуляции. Сначала определить входные схемы, единицы и автоматизацию ROI. |
| Собственная реализация | Использовать идеи обработки ROI, сопоставления поведения и сигналов, shuffle-сравнений. Переписать нужный анализ с явными контрактами; перенос кода требует разрешённой лицензии. |

**Предварительное решение:** Не считать кандидатом ядра генератора. Сохранить как методический материал валидации личиночных/мышечных измерений; не подменять отсутствие данных успешным запуском.

**Квитанции:** [preflight.json](<../research/.work/simulator-evaluation/SIM-004/20261005T123456Z-preflight/preflight.json>).

[Визуальные материалы SIM-004](artifacts/SIM-004/README.md).

<a id="sim-005"></a>
### SIM-005 — emebeiran/connconstr

**Исходники:** [f5f397b88f8dd5c2a5c13558ce6039194a284586](https://github.com/emebeiran/connconstr/tree/f5f397b88f8dd5c2a5c13558ce6039194a284586); связанные ресурсы: ST108, canonical-source, drosophila-connectome-audit, S743.

**Данные и версия:** Teacher/student networks; Zenodo 16618353 figure data

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-005/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-005/source-inventory.json>); [источник](https://github.com/emebeiran/connconstr/tree/f5f397b88f8dd5c2a5c13558ce6039194a284586) |
| Установить окружение и проверить зависимости | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/result.json>) |
| Выполнить штатные или явно обозначенные программные проверки | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/exports/connconstr-fixture/result.json>) |
| Проверить минимальный запуск или CLI | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/result.json>) |
| Выполнить функциональный сценарий с согласованными данными | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/result.json>) |
| Проверить повторяемость короткого сценария и seeds, где применимо | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/exports/connconstr-author-teacher/result.json>); [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/exports/connconstr-fixture/result.json>) |
| Сохранить проверенные визуальные материалы | выполнено | [activity-preview.png](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/activity-preview.png>); [angle-preview.png](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/angle-preview.png>); [simplering2_matrix_final.pdf](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/simplering2_matrix_final.pdf>); [simplering2_matrix_scatter.pdf](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/simplering2_matrix_scatter.pdf>); [simplering2_matrix_spect.pdf](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/simplering2_matrix_spect.pdf>); [simplering2_netAngle_exampleBump_trial_0.pdf](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/simplering2_netAngle_exampleBump_trial_0.pdf>); [simplering2_netAngle_exampleBump_trial_1.pdf](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/simplering2_netAngle_exampleBump_trial_1.pdf>); [simplering2_netAngle_exampleBump_trialFinal_1.pdf](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/simplering2_netAngle_exampleBump_trialFinal_1.pdf>); [simplering2_netAngle_final.pdf](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/simplering2_netAngle_final.pdf>); [simplering2_netAngle_readout_final.pdf](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/simplering2_netAngle_readout_final.pdf>); [simplering2_synws_hist.pdf](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/source/Figs/simplering2_synws_hist.pdf>) |
| Записать итог, ограничения и три варианта применения | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/result.json>); [author-archive.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/author-archive.json>); [extracted-author-data.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/extracted-author-data.json>); [author_dependencies-result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/author_dependencies-result.json>); [author_run-result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/author_run-result.json>); [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/exports/connconstr-fixture/result.json>); [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/exports/connconstr-author-teacher/result.json>) |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

**Итог (2026-10-05):** Установка и pip check, функциональная проверка RNN, авторская модель Figure 1 (300 нейронов) прошли. Авторский сценарий Figure 5 на hemibrain: passed.

**Область проверки:** Программная проверка, авторские синтетические веса и модель центрального комплекса из hemibrain. Не модель всего мозга, тела или человеческого ECAP; не воспроизведение всех результатов статьи.

**Измеренная пиковая RAM, байт:** `{"author_figure5_peak_bytes": 4769677312}`.

**Существенные исправления:**

- Добавлена pandas для авторского сценария; подготовлен каталог Figs и безоконный backend Agg.
- Архив Zenodo 16618353 скачан и проверен по MD5 и SHA-256.
- По решению пользователя сняты ограничение RAM Docker и проверка запаса RAM; сценарий действительно запущен.

**Преимущества:**

- Авторский код обучения connectome-constrained RNN и доступные данные для Figure 1–5.
- Доступ к весам, нейронным состояниям, loss и экспорту NumPy/PyTorch.
- Короткие seeded проверки и восстановление состояния воспроизводимы на CPU.

**Ограничения:**

- Нет тела, среды и физического оператора ECAP.
- Исследовательские монолитные скрипты без штатного тестового пакета; зависимости требуют явного закрепления.
- Плотная матрица полного hemibrain загружается перед выделением небольшой подсети.
- Лицензия архива Zenodo CC BY 4.0 не устанавливает автоматически лицензию всего Git-репозитория.
- Полный авторский сценарий не имеет внешнего задания seed; его повторяемость отдельно не подтверждена.

| Продолжение | Оценка |
|---|---|
| Адаптация | Выделить RNN, обучение и загрузчик подсети в отдельный модуль; заменить плотную подготовку графа при необходимости и закрепить единицы/seed/экспорт. |
| Композиция сервисов | Использовать отдельный компонент обучения представлений рядом с embodied-симулятором и независимым человеческим ECAP-оператором. |
| Собственная реализация | Использовать как методический ориентир и контрольную реализацию; права на перенос кода проверить отдельно. |

**Предварительное решение:** Сохранить как методический кандидат обучения и проверки переносимых представлений. Архитектуру генератора выбирать после испытаний остальных репозиториев.

**Квитанции:** [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/result.json>); [author-archive.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/author-archive.json>); [extracted-author-data.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/extracted-author-data.json>); [author_dependencies-result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/author_dependencies-result.json>); [author_run-result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/author_run-result.json>); [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/exports/connconstr-fixture/result.json>); [result.json](<../research/.work/simulator-evaluation/SIM-005/20261005T123535Z-48648e/exports/connconstr-author-teacher/result.json>).

[Визуальные материалы SIM-005](artifacts/SIM-005/README.md).

<a id="sim-006"></a>
### SIM-006 — eonsystemspbc/fly-brain

**Исходники:** [a3db62f9436074e485c0278290c2164ed6150808](https://github.com/eonsystemspbc/fly-brain/tree/a3db62f9436074e485c0278290c2164ed6150808); связанные ресурсы: ST007, canonical-source, S732.

**Данные и версия:** FlyWire v783 default; separate v630 paper scenario

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-006/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-006/source-inventory.json>); [источник](https://github.com/eonsystemspbc/fly-brain/tree/a3db62f9436074e485c0278290c2164ed6150808) |
| Установить окружение и проверить зависимости | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/result.json>) |
| Выполнить штатные или явно обозначенные программные проверки | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/result.json>) |
| Проверить минимальный запуск или CLI | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/result.json>) |
| Выполнить функциональный сценарий с согласованными данными | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/result.json>) |
| Проверить повторяемость короткого сценария и seeds, где применимо | выполнено | [full-result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/full-result.json>); [software-result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/software-result.json>) |
| Сохранить проверенные визуальные материалы | выполнено | [spike-raster-seed1.png](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/spike-raster-seed1.png>); [spike-raster-seed1.pdf](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/spike-raster-seed1.pdf>) |
| Записать итог, ограничения и три варианта применения | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/result.json>); [pinned-assets.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/pinned-assets.json>); [input-identity.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/input-identity.json>); [dependencies.lock.txt](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/dependencies.lock.txt>); [software-result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/software-result.json>); [full-result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/full-result.json>); [visual-result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/visual-result.json>); [spike-raster-seed1.png](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/spike-raster-seed1.png>); [spike-raster-seed1.pdf](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/spike-raster-seed1.pdf>); [review-evidence.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/review-evidence.json>) |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

**Итог (2026-10-25):** SIM-006 Eon fly-brain запущен на CPU с полным закреплённым FlyWire v783: 138 639 нейронов и 15 091 983 строки связности. Четыре расчёта по 100 мс (seeds 1/2/3/1) завершены; повтор seed 1 совпадает точно, включая Parquet. У PyTorch-варианта выявлены функциональные ограничения, поэтому результат не распространяется на все заявленные возможности.

**Область проверки:** Установка и pip check; CLI; восьминейронные проверки настоящих классов TorchModel и Brian2 runtime; полный граф в неизменённом PyTorch CLI с заданием seeds и диагностикой конечности состояний. Это нейродинамика без тела, среды и человеческого ECAP; длительные сценарии, C++/CUDA/GeNN/NEST и биологическая достоверность не проверены.

**Измеренная пиковая RAM, байт:** `{"functional_container_peak_bytes": 5081124864, "install_container_peak_bytes": 1041461248}`.

**Существенные исправления:**

- Зависимости PyTorch устанавливаются из PyPI с дополнительным официальным CPU-индексом; исходный CPU-only индекс не предоставлял нужную зависимость сборки flit_core.
- Исключённые sparse checkout файлы v783 восстановлены только в рабочую копию; оба Git blob и SHA-256 проверены, upstream чистый.
- Окружение Python 3.10 с numpy 1.26.4, Brian2 2.8.0, PyTorch 2.14.1+cpu; полные разрешённые версии сохранены в dependencies.lock.txt.

**Преимущества:**

- Реальный версионированный коннектом, разреженная матрица и доступ к состояниям LIF-модели
- Штатный экспорт спайков с временем в мс, trial, индексом нейрона и FlyWire ID; сохранены CSV, манифесты, SHA-256, график и соответствие активных ID
- Короткий полный CPU-сценарий воспроизводим; среднее между вариантами реализации не подменяет проверку конкретного backend

**Ограничения:**

- В проверенном PyTorch runner поле neu_slnc не подавляет активность, а neu_exc2 не действует: это подтверждено отдельным программным примером и чтением реализации
- В стандартном TorchModel ноль обучаемых параметров; готового контура предобучения и адаптации нет
- Нет тела, среды, явного ноцицептивного сценария, человеческого рекрутирования и оператора регистрации ECAP
- 100 мс вычислены за 44,792–47,405 с с проверкой конечности каждого состояния; это не оценка чистой скорости backend и не длительная проверка устойчивости
- Корневая лицензия GPL-2.0-or-later и MIT у вложенных материалов Shiu должны учитываться отдельно; условия данных не выводятся автоматически из лицензии кода

| Продолжение | Оценка |
|---|---|
| Адаптация | Рабочий кандидат нейронного компонента. Потребуются явные интерфейсы воздействий, реализация недостающего управления PyTorch, управление состоянием и отдельный обучаемый временной модуль. |
| Композиция сервисов | Можно рассматривать как сервис нейродинамики с версией графа, конфигурацией, seed и экспортом состояний. Тело/среда и человеческий ECAP-оператор должны оставаться отдельными компонентами; межреализационное численное соответствие ещё требуется проверить. |
| Собственная реализация | Полезен как исполняемый ориентир LIF-модели, разреженной связности, формата спайков и контрольных расчётов. Собственная реализация должна воспроизвести согласованные сценарии и явно учитывать лицензии при переносе кода. |

**Предварительное решение:** Сохранить в сравнении как реально запущенный нейронный кандидат с ограничениями PyTorch API. Не выбирать архитектуру генератора до проверки остальных репозиториев.

**Квитанции:** [result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/result.json>); [pinned-assets.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/pinned-assets.json>); [input-identity.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/input-identity.json>); [dependencies.lock.txt](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/dependencies.lock.txt>); [software-result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/software-result.json>); [full-result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/full-result.json>); [visual-result.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/visual-result.json>); [spike-raster-seed1.png](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/spike-raster-seed1.png>); [spike-raster-seed1.pdf](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/exports/eon/spike-raster-seed1.pdf>); [review-evidence.json](<../research/.work/simulator-evaluation/SIM-006/20261025T103703Z-5caefe/review-evidence.json>).

[Визуальные материалы SIM-006](artifacts/SIM-006/README.md).

<a id="sim-007"></a>
### SIM-007 — erankopel/maleCNS-depth

**Исходники:** [e80dcf643beefff08afd936a741ac8cc50723cb4](https://github.com/erankopel/maleCNS-depth/tree/e80dcf643beefff08afd936a741ac8cc50723cb4); связанные ресурсы: canonical-source, S857.

**Данные и версия:** MaleCNS; confirmatory inputs have frozen MD5 and graph SHA256

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-007/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-007/source-inventory.json>); [источник](https://github.com/erankopel/maleCNS-depth/tree/e80dcf643beefff08afd936a741ac8cc50723cb4) |
| Установить окружение и проверить зависимости | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/result.json>) |
| Выполнить штатные или явно обозначенные программные проверки | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/result.json>) |
| Проверить минимальный запуск или CLI | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/result.json>) |
| Выполнить функциональный сценарий с согласованными данными | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/result.json>) |
| Проверить повторяемость короткого сценария и seeds, где применимо | выполнено | [real-graph-result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/exports/malecns-depth/real-graph-result.json>); [synthetic-seeds-result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/exports/malecns-depth/synthetic-seeds-result.json>) |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/result.json>); [dependencies.lock.txt](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/dependencies.lock.txt>); [native_tests.log](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/native_tests.log>); [real-graph-result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/exports/malecns-depth/real-graph-result.json>); [synthetic-seeds-result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/exports/malecns-depth/synthetic-seeds-result.json>); [seed_checks-result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/seed_checks-result.json>); [build-graph-attempt1.log](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/exports/malecns-depth/build-graph-attempt1.log>); [build-graph-attempt2.log](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/exports/malecns-depth/build-graph-attempt2.log>); [review-evidence.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/review-evidence.json>) |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

**Итог (2026-10-25):** SIM-007 maleCNS-depth работает как аналитический инструмент: установка, pip check, штатные проверки границ и интеграционные тесты на синтетических данных прошли. Авторский скрипт дважды построил реальный граф MaleCNS v1.0: 166 700 нейронов, 25 582 938 рёбер, сумма весов 124 177 617. Хеш содержимого совпал с авторским зафиксированным значением cd6bbde8…; повтор полностью совпадает по содержимому массивов.

**Область проверки:** Проверки программного обеспечения и подготовки графа. Отдельно выполнен авторский синтетический генератор с seeds 1/2/3 и повтором 1 (3000 узлов). Реальная подтверждающая серия H1–H5 не воспроизведена этим сценарием. Это не симулятор нейронной динамики, тела или ECAP.

**Измеренная пиковая RAM, байт:** `{"real_graph_preparation_peak_bytes": 1921490944, "native_synthetic_tests_peak_bytes": 1042886656}`.

**Существенные исправления:**

- Среда Python 3.11 согласована с авторской веткой; NumPy 2.4.4, SciPy 1.17.1, pandas 3.0.2 и pyarrow 25.0.1 установлены по закреплённому requirements.
- Три первичных файла MaleCNS v1.0 повторно использованы из проверенного кэша SIM-001; проверены SHA-256 и авторские MD5. Файлы FlyWire v783 не подставлялись.
- Исправлено создание вложенного каталога assets/malecns в инструменте испытаний; регрессионный тест прошёл. Upstream не редактировался.
- Вместо скрипта с абсолютным /home/claude выполнен авторский Python build_graph.py с явным MALECNS_DATA внутри рабочей копии.

**Преимущества:**

- Проверяемые первичные входы, зафиксированные MD5, логический SHA-256 графа и отдельные подтверждающие и исследовательские сценарии
- Штатные проверки сравнивают границы с точными плотными вычислениями и проверяют повторяемость, отказ от перезаписи и обнаружение повреждённых данных
- Потоковая обработка исходной таблицы, компактный NPZ и код подготовки графа с лицензией MIT

**Ограничения:**

- Случайное блуждание и спектральные характеристики графа не являются спайками, биофизическим временем, ноцицепцией или ECAP
- Для полной реальной серии нужны дополнительные syn-partners (около 6,8 ГБ) и отдельный численный запуск H1–H5; они здесь не объявлены воспроизведёнными
- Абсолютные пути авторских shell-скриптов требуют внешней параметризации; готового API генератора и модели тела нет

| Продолжение | Оценка |
|---|---|
| Адаптация | Подходит для подготовки и контроля структуры графов; не подходит как непосредственное ядро генерации нейродинамики. Понадобятся стабильная схема входов и пакетный интерфейс. |
| Композиция сервисов | Рассматривать как отдельную пакетную стадию подготовки и структурной диагностики перед нейронным симулятором. Версия графа и определение весов должны передаваться явно. |
| Собственная реализация | Использовать формат компактного графа, проверки входных хешей, независимые эталонные вычисления и разделение подтверждающего/исследовательского анализа. Динамический solver и ECAP-оператор потребуются отдельно. |

**Предварительное решение:** Сохранить как проверенный компонент подготовки и диагностики коннектома, а не как альтернативу нейронному симулятору. Выбор общей архитектуры остаётся открытым.

**Квитанции:** [result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/result.json>); [dependencies.lock.txt](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/dependencies.lock.txt>); [native_tests.log](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/native_tests.log>); [real-graph-result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/exports/malecns-depth/real-graph-result.json>); [synthetic-seeds-result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/exports/malecns-depth/synthetic-seeds-result.json>); [seed_checks-result.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/seed_checks-result.json>); [build-graph-attempt1.log](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/exports/malecns-depth/build-graph-attempt1.log>); [build-graph-attempt2.log](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/exports/malecns-depth/build-graph-attempt2.log>); [review-evidence.json](<../research/.work/simulator-evaluation/SIM-007/20261025T110749Z-7c38a9/review-evidence.json>).

[Визуальные материалы SIM-007](artifacts/SIM-007/README.md).

<a id="sim-008"></a>
### SIM-008 — flyconnectome/2025malecns

**Исходники:** [67767d2233657983993ff6c2be48e836a935863c](https://github.com/flyconnectome/2025malecns/tree/67767d2233657983993ff6c2be48e836a935863c); связанные ресурсы: drosophila-connectome-audit.

**Данные и версия:** MaleCNS supplemental exports; thresholds alter neuron/edge counts

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-008/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-008/source-inventory.json>); [источник](https://github.com/flyconnectome/2025malecns/tree/67767d2233657983993ff6c2be48e836a935863c) |
| Установить окружение и проверить зависимости | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/result.json>) |
| Выполнить штатные или явно обозначенные программные проверки | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/result.json>) |
| Проверить минимальный запуск или CLI | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/result.json>) |
| Выполнить функциональный сценарий с согласованными данными | блокировано | [result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/result.json>) |
| Проверить повторяемость короткого сценария и seeds, где применимо | выполнено | [software-result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/exports/malecns-notebook/software-result.json>) |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/result.json>); [dependencies.lock.txt](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/dependencies.lock.txt>); [pinned-supplements.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/pinned-supplements.json>); [software-result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/exports/malecns-notebook/software-result.json>); [supplements-result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/exports/malecns-notebook/supplements-result.json>); [input-identity-result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/exports/malecns-notebook/input-identity-result.json>); [functional-retry-docker-events.jsonl](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/functional-retry-docker-events.jsonl>); [kernel-memory-observation.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/kernel-memory-observation.json>); [functional-f442b317.log](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/functional-f442b317.log>); [review-evidence.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/review-evidence.json>) |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

**Итог (2026-10-25):** SIM-008 установлен; шесть закреплённых дополнительных таблиц читаются. Входы MaleCNS v0.9 проверены по размеру, SHA-256 и первичному CRC32C GCS. После исправлений малый программный пример воспроизводим. Полный ноутбук на этой машине не завершён: ядро WSL подтвердило global_oom и завершило Python нашего контейнера при загрузке таблицы связности (код 137).

**Область проверки:** Проверка форматов ресурсов, целостности и версии входов, воспроизведение ошибок и исправлений на шестистрочном примере; действительная попытка полного ноутбука. Это выпуск дополнительных данных и структурный анализ, не симулятор нейродинамики.

**Измеренная пиковая RAM, байт:** `{"full_notebook_observed_peak_bytes": 5257150464, "measurement_note": "Максимальное наблюдение cgroup peak; терминальный пик может быть выше"}`.

**Существенные исправления:**

- В исходном ноутбуке отсутствует import os; ошибка воспроизведена до добавления модуля в контекст исполнения рабочей копии.
- Пропущенные метки приводят к TypeError в строковых фильтрах. Исходные строковые условия сохранены, к ним допускаются только значения str; порог веса >=5 не изменён.
- Исключённые sparse checkout таблицы восстановлены из шести закреплённых Git blob только в .work; v1.0 таблицы не подставлялись в v0.9 ноутбук.
- Исправлен монитор испытаний: тайм-аут отдельного чтения телеметрии теперь не завершает живой процесс. Повторный полный запуск прерван global_oom, не монитором.

**Преимущества:**

- Первичные дополнительные таблицы по MaleCNS: классы DN/AN, слои обхода графа, зрительные колонки и показатели качества/полноты реконструкции
- Проверяемые версии, Git blob, поколения объектов GCS, CRC32C и SHA-256 входов
- Небольшой прозрачный ноутбук подсчёта нейронов, рёбер и агрегации по типам

**Ограничения:**

- Нет динамического solver, стимуляции, тела, среды и ECAP-оператора
- Полный ноутбук одновременно разворачивает большую таблицу и дополнительные столбцы меток; действительная попытка завершилась из-за памяти WSL
- Нет закреплённого окружения и штатного тестового пакета; обнаружены ошибки самодостаточного запуска и обработки пропусков
- Наличие таблиц и чтение данных не воспроизводят расчёты maxflow или 10 000 обходов; такие результаты не объявлены повторёнными
- Отдельная лицензия переиспользования Git-репозитория не установлена по исходникам

| Продолжение | Оценка |
|---|---|
| Адаптация | Рассматривать для подготовки аннотаций и проверок полноты/структуры, с явной версией данных и обработкой пропусков. Для полного подсчёта нужна подтверждённая потоковая реализация либо подходящая вычислительная среда. |
| Композиция сервисов | Подходит как версионированный пакет метаданных или офлайн-стадия подготовки данных; отдельного сервиса симуляции здесь нет. |
| Собственная реализация | Использовать структуру таблиц и правила подсчёта как требования к своим загрузчикам/тестам, не переносить в генератор предположение об эквивалентности структурных слоёв и времени нейродинамики. |

**Предварительное решение:** Сохранить как полезный источник дополнительных данных и правил структурной проверки. Полный ноутбук на текущей машине не принят; переход к следующему кандидату не подменяет этот результат успешным запуском.

**Квитанции:** [result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/result.json>); [dependencies.lock.txt](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/dependencies.lock.txt>); [pinned-supplements.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/pinned-supplements.json>); [software-result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/exports/malecns-notebook/software-result.json>); [supplements-result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/exports/malecns-notebook/supplements-result.json>); [input-identity-result.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/exports/malecns-notebook/input-identity-result.json>); [functional-retry-docker-events.jsonl](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/functional-retry-docker-events.jsonl>); [kernel-memory-observation.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/kernel-memory-observation.json>); [functional-f442b317.log](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/functional-f442b317.log>); [review-evidence.json](<../research/.work/simulator-evaluation/SIM-008/20261025T113426Z-3ab3f7/review-evidence.json>).

[Визуальные материалы SIM-008](artifacts/SIM-008/README.md).

<a id="sim-009"></a>
### SIM-009 — gauravvvvvvvvvv/flybox

**Исходники:** [5880d221e21b1f3385b7246a6ffc3b2cf0029c2c](https://github.com/gauravvvvvvvvvv/flybox/tree/5880d221e21b1f3385b7246a6ffc3b2cf0029c2c); связанные ресурсы: ST107, canonical-source, drosophila-connectome-audit, S737.

**Данные и версия:** 166700 neurons; 25088107 edges; external export commit 03358c075000af5379e405b244dd31f1a0fd1401

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-009/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-009/source-inventory.json>); [источник](https://github.com/gauravvvvvvvvvv/flybox/tree/5880d221e21b1f3385b7246a6ffc3b2cf0029c2c) |
| Установить окружение и проверить зависимости | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/result.json>) |
| Выполнить штатные или явно обозначенные программные проверки | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/result.json>) |
| Проверить минимальный запуск или CLI | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/result.json>) |
| Выполнить функциональный сценарий с согласованными данными | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/result.json>) |
| Проверить повторяемость короткого сценария и seeds, где применимо | выполнено | [browser-result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/exports/flybox/browser-result.json>); [connectome-result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/exports/flybox/connectome-result.json>) |
| Сохранить проверенные визуальные материалы | выполнено | [browser-play.png](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/exports/flybox/browser-play.png>); [browser-lab.png](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/exports/flybox/browser-lab.png>) |
| Записать итог, ограничения и три варианта применения | выполнено | [result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/result.json>); [dependencies.lock.txt](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/dependencies.lock.txt>); [npm-dependency-tree.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/npm-dependency-tree.json>); [node-version.txt](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/node-version.txt>); [connectome-result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/exports/flybox/connectome-result.json>); [browser-result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/exports/flybox/browser-result.json>); [experiment-export.json.gz](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/exports/flybox/experiment-export.json.gz>) |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T141017Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T141017Z.json>) |

**Итог (2026-10-25):** FLYBOX запускается в браузере с реальным компактным MaleCNS: 166700 нейронов и 25088107 связей. Отдельно прошли 17 Python-тестов MockBrain, TypeScript/browser audit и расчёт неизменённого нейронного движка. Seeds 1/2/3/1 повторены в Node и браузерном PURE LAB; численные результаты seed 1 совпали.

**Область проверки:** Установка и версии, pip check, Python MockBrain tests, tsc и штатный browser audit, сборка Vite, полный компактный граф в Node, настоящий Edge/WebWorker, pause/step/reset, checkpoint времени, API стимуляции/подавления/восстановления LC4, изменение мира, анатомический sample и JSON-экспорт.

**Измеренная пиковая RAM, байт:** `{"container_peak_install_bytes": 608681984, "container_peak_neural_probe_bytes": 525660160, "browser_peak_bytes": null, "scope": "Docker cgroup phases only; browser RAM not measured"}`.

**Существенные исправления:**

- Подготовлен воспроизводимый Node 22/Python образ; отсутствующий upstream npm lock создаётся только в рабочей копии перед npm ci.
- pytest использует capture=sys и временные каталоги внутри прогона для Windows bind mount.
- Пропущенный sparse checkout vercel.json восстановлен из закреплённого Git blob в рабочую копию.
- Проверка подавления читает опубликованный API populations, поскольку FlyFrame не раскрывает внутренний silenced.
- Недоступная локальная Vercel-аналитика записана как необязательная телеметрия; основные ресурсы и JavaScript работают без ошибок.

**Преимущества:**

- Браузерная среда и полный компактный граф работают локально на CPU; предусмотрены PLAY и явно отделённый PURE LAB.
- Есть стимуляция, подавление, seeded lesions, снимки/ветвление и экспорт; Node-проверки подтвердили повторяемость, восстановление нейронного состояния и нулевой рекуррентный ток при удалении всех рёбер.
- Реальные 140638 soma-позиций доступны для инспекции; сохранены скриншоты сцены и нейронного интерфейса.

**Ограничения:**

- PLAY содержит игровые двигательные эвристики, а тело — упрощённая двумерная сцена, не биомеханическая модель Drosophila.
- Веса квантизованы в 8 бит и логарифмически кодированы; напряжения нормированы. Компактный экспорт не объявляется эквивалентным исходному графу MaleCNS с 25582938 строками.
- Python-тесты используют MockBrain и не доказывают эквивалентность Python и TypeScript. В браузере проверено восстановление времени; полное совпадение будущей динамики после rewind там отдельно не установлено.
- Запуск и программные вмешательства не подтверждают биологическую причинность поведения; человеческого оператора ECAP нет.
- Необязательный скрипт Vercel отсутствует в локальной раздаче; пиковая RAM браузера и VRAM не измерены. Лицензии Apache-2.0 проекта, MIT движка и права на внешний экспорт рассматриваются раздельно.

| Продолжение | Оценка |
|---|---|
| Адаптация | Подходит для интерактивного прототипа и изучения управляемых нейронных состояний. Для генератора нужны устойчивый API экспорта, проверенные сенсорно-моторные отображения, единицы и длительные сценарии без PLAY-эвристик. |
| Композиция сервисов | Кандидат на отдельный браузерный интерфейс наблюдения и вмешательств. Сервис нейродинамики, биомеханику тела и человеческий ECAP-оператор следует сопрягать через проверенные контракты; готовая совместимость с другими SIM не установлена. |
| Собственная реализация | Полезны контракты worker RPC, воспроизводимые вмешательства и визуальная инспекция как технические образцы. Собственная реализация даст контроль над динамикой и единицами, но потребует заново проверять наблюдение, экспорт и сенсорно-моторную связь. |

**Предварительное решение:** Сохранить как работоспособный интерактивный кандидат; выбирать основу генератора после сравнения остальных репозиториев. Не использовать PLAY-поведение как биологическую разметку.

**Квитанции:** [result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/result.json>); [dependencies.lock.txt](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/dependencies.lock.txt>); [npm-dependency-tree.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/npm-dependency-tree.json>); [node-version.txt](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/node-version.txt>); [connectome-result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/exports/flybox/connectome-result.json>); [browser-result.json](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/exports/flybox/browser-result.json>); [experiment-export.json.gz](<../research/.work/simulator-evaluation/SIM-009/20261025T115431Z-143840/exports/flybox/experiment-export.json.gz>).

[Визуальные материалы SIM-009](artifacts/SIM-009/README.md).

<a id="sim-010"></a>
### SIM-010 — hsseung/OpticLobe.jl

**Исходники:** [3352e97c37b0f96ab08f27b70b4420f3d4ac2726](https://github.com/hsseung/OpticLobe.jl/tree/3352e97c37b0f96ab08f27b70b4420f3d4ac2726); связанные ресурсы: canonical-source, S888.

**Данные и версия:** Optic-lobe connectivity and Julia paper data; analysis only

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-010/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-010/source-inventory.json>); [источник](https://github.com/hsseung/OpticLobe.jl/tree/3352e97c37b0f96ab08f27b70b4420f3d4ac2726) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-010](artifacts/SIM-010/README.md).

<a id="sim-011"></a>
### SIM-011 — htem/BANC-project

**Исходники:** [e31a2e26b9937dca72e5ca1c1960df6454d76114](https://github.com/htem/BANC-project/tree/e31a2e26b9937dca72e5ca1c1960df6454d76114); связанные ресурсы: drosophila-connectome-audit.

**Данные и версия:** BANC materialisations v626/v850/v888; must match the selected scenario

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-011/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-011/source-inventory.json>); [источник](https://github.com/htem/BANC-project/tree/e31a2e26b9937dca72e5ca1c1960df6454d76114) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-011](artifacts/SIM-011/README.md).

<a id="sim-012"></a>
### SIM-012 — htem/FANC_auto_recon

**Исходники:** [89d9769457583051e3ec9ec7b34a5f3575537bf5](https://github.com/htem/FANC_auto_recon/tree/89d9769457583051e3ec9ec7b34a5f3575537bf5); связанные ресурсы: canonical-source, drosophila-connectome-audit, S773.

**Данные и версия:** FANC data access and coordinate transforms; reconstruction/preparation

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-012/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-012/source-inventory.json>); [источник](https://github.com/htem/FANC_auto_recon/tree/89d9769457583051e3ec9ec7b34a5f3575537bf5) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-012](artifacts/SIM-012/README.md).

<a id="sim-013"></a>
### SIM-013 — jajmcallister/Conn_ESN_Paper

**Исходники:** [55b9069b919951c39dfc3a342b7b31e6cb575838](https://github.com/jajmcallister/Conn_ESN_Paper/tree/55b9069b919951c39dfc3a342b7b31e6cb575838); связанные ресурсы: canonical-source, S872.

**Данные и версия:** Author ESN weight matrices and task inputs; Julia 1.11

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-013/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-013/source-inventory.json>); [источник](https://github.com/jajmcallister/Conn_ESN_Paper/tree/55b9069b919951c39dfc3a342b7b31e6cb575838) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-013](artifacts/SIM-013/README.md).

<a id="sim-014"></a>
### SIM-014 — JNLiew/flylif_orientation_maps

**Исходники:** [d73b18712579c969feba625ecfd3df52f4d328f4](https://github.com/JNLiew/flylif_orientation_maps/tree/d73b18712579c969feba625ecfd3df52f4d328f4); связанные ресурсы: canonical-source, S841.

**Данные и версия:** FlyWire visual LIF model; explicit author data files required

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-014/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-014/source-inventory.json>); [источник](https://github.com/JNLiew/flylif_orientation_maps/tree/d73b18712579c969feba625ecfd3df52f4d328f4) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-014](artifacts/SIM-014/README.md).

<a id="sim-015"></a>
### SIM-015 — legacyindiesubmissions-ai/claude-fly

**Исходники:** [3a035275148e97539711728422548bffe2a77566](https://github.com/legacyindiesubmissions-ai/claude-fly/tree/3a035275148e97539711728422548bffe2a77566); связанные ресурсы: ST008, canonical-source, drosophila-connectome-audit, S292.

**Данные и версия:** FlyWire v783 and plastic LFS weights; legacy FlyGym imports

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-015/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-015/source-inventory.json>); [источник](https://github.com/legacyindiesubmissions-ai/claude-fly/tree/3a035275148e97539711728422548bffe2a77566) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-015](artifacts/SIM-015/README.md).

<a id="sim-016"></a>
### SIM-016 — MakazhanAlpamys/soup-connectome

**Исходники:** [40aa07f87995a7061f75f92f8ddd0465ede89577](https://github.com/MakazhanAlpamys/soup-connectome/tree/40aa07f87995a7061f75f92f8ddd0465ede89577); связанные ресурсы: ST012.

**Данные и версия:** 4-neuron native fixture versus separate MaleCNS v1.0 Feather/SCX scenario

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-016/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-016/source-inventory.json>); [источник](https://github.com/MakazhanAlpamys/soup-connectome/tree/40aa07f87995a7061f75f92f8ddd0465ede89577) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-016](artifacts/SIM-016/README.md).

<a id="sim-017"></a>
### SIM-017 — murthylab/flywire-network-analysis

**Исходники:** [ee4944c03429edf857a6b10bcf98bea7dcef35b8](https://github.com/murthylab/flywire-network-analysis/tree/ee4944c03429edf857a6b10bcf98bea7dcef35b8); связанные ресурсы: ST003.

**Данные и версия:** FlyWire v630; graph-tool network analyses, not neural dynamics

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-017/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-017/source-inventory.json>); [источник](https://github.com/murthylab/flywire-network-analysis/tree/ee4944c03429edf857a6b10bcf98bea7dcef35b8) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-017](artifacts/SIM-017/README.md).

<a id="sim-018"></a>
### SIM-018 — nalin-dhiman/Connectome-Constrained-Neural-Networks

**Исходники:** [336e0d12a6edd92a7340cfffb71985a3879055ce](https://github.com/nalin-dhiman/Connectome-Constrained-Neural-Networks/tree/336e0d12a6edd92a7340cfffb71985a3879055ce); связанные ресурсы: drosophila-connectome-audit.

**Данные и версия:** Connectome-constrained visual network and figure reproduction data

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-018/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-018/source-inventory.json>); [источник](https://github.com/nalin-dhiman/Connectome-Constrained-Neural-Networks/tree/336e0d12a6edd92a7340cfffb71985a3879055ce) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-018](artifacts/SIM-018/README.md).

<a id="sim-019"></a>
### SIM-019 — nalin-dhiman/ScaleBreak-FlyVis

**Исходники:** [24c87489efdca64970ecbe93efc683b68f778cdf](https://github.com/nalin-dhiman/ScaleBreak-FlyVis/tree/24c87489efdca64970ecbe93efc683b68f778cdf); связанные ресурсы: canonical-source, S853.

**Данные и версия:** Pretrained FlyVis responses and visual scale stimuli; comparator

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-019/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-019/source-inventory.json>); [источник](https://github.com/nalin-dhiman/ScaleBreak-FlyVis/tree/24c87489efdca64970ecbe93efc683b68f778cdf) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-019](artifacts/SIM-019/README.md).

<a id="sim-020"></a>
### SIM-020 — NeLy-EPFL/flygym

**Исходники:** [38c8ec61034cd59bc5ba0de20688d4a3c0000d60](https://github.com/NeLy-EPFL/flygym/tree/38c8ec61034cd59bc5ba0de20688d4a3c0000d60); связанные ресурсы: ST106, canonical-source, S734.

**Данные и версия:** FlyGym 2.1.0; body/physics assets, no built-in whole-brain connectome

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-020/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-020/source-inventory.json>); [источник](https://github.com/NeLy-EPFL/flygym/tree/38c8ec61034cd59bc5ba0de20688d4a3c0000d60) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-020](artifacts/SIM-020/README.md).

<a id="sim-021"></a>
### SIM-021 — NeLy-EPFL/flygym-gymnasium

**Исходники:** [d285260a1c8a7b3494150cd1590f2c9fe4b5e06b](https://github.com/NeLy-EPFL/flygym-gymnasium/tree/d285260a1c8a7b3494150cd1590f2c9fe4b5e06b); связанные ресурсы: official-FlyGym-1.x-compatibility.

**Данные и версия:** FlyGym Gymnasium 1.3.2; separate import namespace and MuJoCo 3.2.7

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-021/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-021/source-inventory.json>); [источник](https://github.com/NeLy-EPFL/flygym-gymnasium/tree/d285260a1c8a7b3494150cd1590f2c9fe4b5e06b) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-021](artifacts/SIM-021/README.md).

<a id="sim-022"></a>
### SIM-022 — Neuromorphicism/fly-brain-snntorch

**Исходники:** [fe55fb0cff275a2b6b54926524c8d831838e32fc](https://github.com/Neuromorphicism/fly-brain-snntorch/tree/fe55fb0cff275a2b6b54926524c8d831838e32fc); связанные ресурсы: ST105, canonical-source, S733.

**Данные и версия:** FlyWire v630; sparse default (~280MB author estimate), dense alternative (~60GB)

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-022/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-022/source-inventory.json>); [источник](https://github.com/Neuromorphicism/fly-brain-snntorch/tree/fe55fb0cff275a2b6b54926524c8d831838e32fc) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-022](artifacts/SIM-022/README.md).

<a id="sim-023"></a>
### SIM-023 — nftechie/doomfly

**Исходники:** [71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33](https://github.com/nftechie/doomfly/tree/71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33); связанные ресурсы: ST084, canonical-source, drosophila-connectome-audit, S200.

**Данные и версия:** MaleCNS, compiled engine and ViZDoom; game damage is not biological nociception

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-023/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-023/source-inventory.json>); [источник](https://github.com/nftechie/doomfly/tree/71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-023](artifacts/SIM-023/README.md).

<a id="sim-024"></a>
### SIM-024 — philshiu/Drosophila_brain_model

**Исходники:** [91bdd1e7dcf193f3e7ca5a8933497fcef63b7960](https://github.com/philshiu/Drosophila_brain_model/tree/91bdd1e7dcf193f3e7ca5a8933497fcef63b7960); связанные ресурсы: ST010.

**Данные и версия:** FlyWire v630 default; neuronal activation/silencing, no body/environment

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-024/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-024/source-inventory.json>); [источник](https://github.com/philshiu/Drosophila_brain_model/tree/91bdd1e7dcf193f3e7ca5a8933497fcef63b7960) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-024](artifacts/SIM-024/README.md).

<a id="sim-025"></a>
### SIM-025 — rdarie/modular-bionic-interface-2026

**Исходники:** [604d17fe1d39a6618fd8f26694922a823aeed8c8](https://github.com/rdarie/modular-bionic-interface-2026/tree/604d17fe1d39a6618fd8f26694922a823aeed8c8); связанные ресурсы: canonical-source, S875.

**Данные и версия:** Benchtop and neural-interface recordings from OSF 9hxwe; not an ECAP forward simulator

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-025/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-025/source-inventory.json>); [источник](https://github.com/rdarie/modular-bionic-interface-2026/tree/604d17fe1d39a6618fd8f26694922a823aeed8c8) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-025](artifacts/SIM-025/README.md).

<a id="sim-026"></a>
### SIM-026 — seung-lab/FlyConnectome

**Исходники:** [9b1790b5553082e1f57921790564c7aae7c9c99a](https://github.com/seung-lab/FlyConnectome/tree/9b1790b5553082e1f57921790564c7aae7c9c99a); связанные ресурсы: ST002.

**Данные и версия:** CAVE/cloudvolume FlyWire access tutorials; no simulator

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-026/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-026/source-inventory.json>); [источник](https://github.com/seung-lab/FlyConnectome/tree/9b1790b5553082e1f57921790564c7aae7c9c99a) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-026](artifacts/SIM-026/README.md).

<a id="sim-027"></a>
### SIM-027 — smpuglie/Pugliese_2026

**Исходники:** [10e7661bf414ba7b4c2edf795cd36d0f878c17c0](https://github.com/smpuglie/Pugliese_2026/tree/10e7661bf414ba7b4c2edf795cd36d0f878c17c0); связанные ресурсы: drosophila-connectome-audit.

**Данные и версия:** VNC/JAX model; exact lineage of the four S740 matrices still unresolved

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-027/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-027/source-inventory.json>); [источник](https://github.com/smpuglie/Pugliese_2026/tree/10e7661bf414ba7b4c2edf795cd36d0f878c17c0) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-027](artifacts/SIM-027/README.md).

<a id="sim-029"></a>
### SIM-029 — snedea/flybrain

**Исходники:** [9191824d17871b7851645782d53d23f213ddb938](https://github.com/snedea/flybrain/tree/9191824d17871b7851645782d53d23f213ddb938); связанные ресурсы: ST009.

**Данные и версия:** FlyWire FAFB v783 author binary; reduced legacy tests are a separate scenario

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-029/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-029/source-inventory.json>); [источник](https://github.com/snedea/flybrain/tree/9191824d17871b7851645782d53d23f213ddb938) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-029](artifacts/SIM-029/README.md).

<a id="sim-030"></a>
### SIM-030 — Stavros963/fcta

**Исходники:** [af8e451d9010294c185b966c953616b212f0294c](https://github.com/Stavros963/fcta/tree/af8e451d9010294c185b966c953616b212f0294c); связанные ресурсы: canonical-source, S854.

**Данные и версия:** Sealed larval-connectome result bundle; complete numerical pipeline not public at this pin

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-030/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-030/source-inventory.json>); [источник](https://github.com/Stavros963/fcta/tree/af8e451d9010294c185b966c953616b212f0294c) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-030](artifacts/SIM-030/README.md).

<a id="sim-031"></a>
### SIM-031 — TuragaLab/flyvis

**Исходники:** [92b3845cc426dd309a1a0e1b3890156c42e14021](https://github.com/TuragaLab/flyvis/tree/92b3845cc426dd309a1a0e1b3890156c42e14021); связанные ресурсы: drosophila-connectome-audit.

**Данные и версия:** Visual-system DMN and pretrained ensemble; not a whole-body/whole-brain simulator

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-031/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-031/source-inventory.json>); [источник](https://github.com/TuragaLab/flyvis/tree/92b3845cc426dd309a1a0e1b3890156c42e14021) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-031](artifacts/SIM-031/README.md).

<a id="sim-032"></a>
### SIM-032 — TuragaLab/wormvae

**Исходники:** [15b58bff08bdf4eb04709434d766fca6835d7d79](https://github.com/TuragaLab/wormvae/tree/15b58bff08bdf4eb04709434d766fca6835d7d79); связанные ресурсы: ST109.

**Данные и версия:** C. elegans latent model; different organism, Python3.6/PyTorch1.8 environment

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-032/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-032/source-inventory.json>); [источник](https://github.com/TuragaLab/wormvae/tree/15b58bff08bdf4eb04709434d766fca6835d7d79) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-032](artifacts/SIM-032/README.md).

<a id="sim-033"></a>
### SIM-033 — YijieYin/connectome_data_prep

**Исходники:** [a4df3b0d5345d2a34dac813f897d8427f6a6eb45](https://github.com/YijieYin/connectome_data_prep/tree/a4df3b0d5345d2a34dac813f897d8427f6a6eb45); связанные ресурсы: ST004.

**Данные и версия:** Selected adult/larval sparse matrices and metadata; data preparation only

**Лицензии:** [source-inventory.json](<../research/.work/simulator-evaluation/SIM-033/source-inventory.json>); хеши файлов — в реестре.

| Проверка | Состояние | Основание |
|---|---|---|
| Проверить закреплённые исходники, зависимости и лицензию | выполнено | [source-inventory.json](<../research/.work/simulator-evaluation/SIM-033/source-inventory.json>); [источник](https://github.com/YijieYin/connectome_data_prep/tree/a4df3b0d5345d2a34dac813f897d8427f6a6eb45) |
| Установить окружение и проверить зависимости | не проверено | — |
| Выполнить штатные или явно обозначенные программные проверки | не проверено | — |
| Проверить минимальный запуск или CLI | не проверено | — |
| Выполнить функциональный сценарий с согласованными данными | не проверено | — |
| Проверить повторяемость короткого сценария и seeds, где применимо | не проверено | — |
| Сохранить проверенные визуальные материалы | не проверено | — |
| Записать итог, ограничения и три варианта применения | не проверено | — |
| Удалить временные окружения, кэши и ненужные ресурсы запуска | выполнено | [cleanup-20261025T123716Z.json](<../research/.work/simulator-evaluation/maintenance/cleanup-20261025T123716Z.json>) |

Итоговый разбор не завершён. Команды и результаты отдельных фаз находятся в реестре; успешная фаза не подтверждает остальные функции проекта.

[Визуальные материалы SIM-033](artifacts/SIM-033/README.md).
