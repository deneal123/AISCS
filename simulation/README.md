# Симуляторы и подготовка генератора

Подключённые исходники находятся в `sidecars/`. Их commits и происхождение перечислены в [registry.json](registry.json), назначения и условия проверки — в [evaluation-report.md](evaluation-report.md).

Нейродинамика Drosophila, тело и среда, перенос представлений и человеческий оператор ECAP остаются отдельными частями исследования. Выбор реализации генератора отложен до функциональных испытаний.

## Проверки

SIM-003 Infinite Sugar прошёл штатные тесты и настоящий браузерный запуск Edge/WebGL с поставляемым графом 139 255 нейронов / 2 700 513 связей. Детальные квитанции и оценка вариантов — в [сводке](evaluation-report.md#итоги-запусков-и-варианты-использования). SIM-004 имеет подтверждённые отсутствующие MATLAB/Octave и входные данные. SIM-005 завершил авторский сценарий на hemibrain (1500 эпох); следующий кандидат — SIM-006. Восстановление исключённых sparse checkout файлов SIM-003 выполняется автоматически в рабочую копию; upstream остаётся чистым.

SIM-001 прошёл короткий запуск полного коннектома. SIM-002 установлен, импорт модели исправлен явной зависимостью `brainscale==0.1.0`; функциональный расчёт требует авторских обработанных данных. Актуальные границы и три варианта применения каждого испытанного кандидата: [итоги запусков](evaluation-report.md#итоги-запусков-и-варианты-использования). По решению пользователя текущие испытания выполняются без ограничения RAM контейнера и без проверки запаса RAM перед запуском. Флаг `--no-memory-limit` также явно задаёт этот режим для воспроизведения. Оценки памяти не служат основанием для пропуска; фактические ошибки сохраняются в квитанциях.

Из корня суперпроекта, PowerShell:

```powershell
research/.venv/Scripts/python.exe -B -X utf8 simulation/inventory.py
research/.venv/Scripts/python.exe -B -X utf8 simulation/acquire.py
research/.venv/Scripts/python.exe -B -X utf8 simulation/inspect_sources.py
research/.venv/Scripts/python.exe -B -X utf8 simulation/asset_probe.py
research/.venv/Scripts/python.exe -B -X utf8 simulation/asset_probe.py --validate-only
research/.venv/Scripts/python.exe -B -X utf8 simulation/build_profiles.py
research/.venv/Scripts/python.exe -B -X utf8 simulation/simctl.py preflight
research/.venv/Scripts/python.exe -B -X utf8 simulation/simctl.py evaluate --id SIM-016
research/.venv/Scripts/python.exe -B -X utf8 simulation/simctl.py evaluate --id SIM-029
research/.venv/Scripts/python.exe -B -X utf8 simulation/simctl.py verify
research/.venv/Scripts/python.exe -B -X utf8 simulation/report.py
```

Для остальных сред используются команды из [profiles.json](profiles.json). Запуск без `--id` выполняет их последовательно. CPU-профили не используют GPU. Отсутствующие входы, неподготовленные среды и отказ допуска фиксируются как блокировки.

Испытания возобновлены по порядку ID. Fly Arena установлена, `pip check`, семь штатных тестов и CLI прошли. Seeds 1, 2 и 3 завершили body-demo. Повторяемость seed 1 подтверждена двумя завершёнными попытками: совпадают все 300 численных строк. Дополнительный повтор остановлен защитой RAM; очередь остановлена. Разрешённые версии зависимостей сохранены в `dependencies.lock.txt` прогона. SIM-002 проверен отдельно в пределах доступного корпуса; следующий кандидат — SIM-003.

Для повторной проверки установленного контура после освобождения памяти:

```powershell
research/.venv/Scripts/python.exe -B -X utf8 simulation/simctl.py evaluate --id SIM-001 --resume research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc
```

`--resume` проверяет commit, исходники и наличие lock-файла; сохраняет принятую установку и неизменившиеся успешные тесты. Функциональные испытания выполняются заново в отдельном каталоге экспорта. Профили остальных кандидатов пока не подтверждают работоспособность сред.

Контур базы знаний проверен и затем остановлен для освобождения памяти; индекс сохранён. После проверки ресурса его можно запустить из `research/`:

```powershell
docker compose --env-file .knowledge/runtime.env -f compose.knowledge.yaml --profile knowledge up -d --wait
```

Файл `runtime.env` остаётся локальным. Не запускайте базу одновременно с вычислительной проверкой, если это нарушает резерв RAM.

`acquire.py` сохраняет закреплённый commit при повторном запуске. Частичный checkout включает исходники; крупные данные и веса загружаются отдельно в `.work/`. На новом компьютере используйте этот скрипт для sidecars: полный рекурсивный checkout может скачать многогигабайтные данные. Уже подключённые основные сабмодули суперпроекта не изменяются.

## Хранение

| Место | Назначение |
|---|---|
| `sidecars/` | Чистые закреплённые upstream-сабмодули |
| `registry.json` | Источники, commits, лицензии, зависимости, актуальные статусы |
| `profiles.json` | Изолированные среды и точные команды |
| `assessment.json` | Краткое сравнение и проверенные маршруты данных |
| `research/.work/simulator-evaluation/<SIM-ID>/<run>/` | Рабочая копия, окружение, логи, результаты и экспорт |
| `research/.work/simulator-evaluation/<SIM-ID>/assets/` | Зарегистрированные файлы и квитанции загрузки |

Полные инвентари и начальные SHA256 находятся в `.work/`. Не запускайте upstream-код из чистого сабмодуля. Повторная сборка отчёта заменяет текущую сводку без накопления архивов.

Открытые работы: [TODO.md](TODO.md). Будущий генератор: [требования](generator-requirements.md).
