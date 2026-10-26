# Испытания симуляторов

Здесь сравниваются 32 закреплённых репозитория для будущего генератора данных. Установка, функциональный запуск и научная достоверность учитываются отдельно. Выбор реализации генератора остаётся открытым.

Версия среза испытаний — **1.0.0**. Первичный разбор выполнен для всех 32 кандидатов. Повторно рассмотрены все 26 ранее открытых проверок: восемь закрыты, 18 остаются открытыми с указанными причинами. Новый запуск и повторное чтение исходных оснований различаются в [отчёте](REPORT.md).

| Где | Что находится |
|---|---|
| [TODO.md](TODO.md) | Выполненные и открытые проверки по SIM |
| [REPORT.md](REPORT.md) | Итоги, ограничения и варианты использования |
| [artifacts/](artifacts/README.md) | Графики, видео и реальные скриншоты отдельно для каждого SIM |
| [data/registry.json](data/registry.json) | Основная запись: commit, происхождение, квитанции и разбор результата |
| [data/profiles.json](data/profiles.json) | Исполняемые команды и входные данные |
| [data/assessment.json](data/assessment.json) | Автоматически сформированное состояние проверок |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Порядок испытаний и правила ведения материалов |
| [docs/generator-requirements.md](docs/generator-requirements.md) | Требования к будущему генератору |
| [docs/nociception-and-recording.md](docs/nociception-and-recording.md) | Что умеют проверенные модели: тело, спайки, ноцицептивные задачи и CAP |
| `scripts/`, `environments/`, `tests/` | Инструменты, определения окружений и их проверки |
| `sidecars/` | Закреплённые исходники сабмодулей |

Команды из корня суперпроекта:

```powershell
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/simctl.py preflight
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/cleanup.py --apply --docker
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/simctl.py evaluate --id SIM-011 --no-memory-limit --no-host-reserve
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/publish_artifacts.py
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/report.py
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/check.py
```

После завершения SIM повторить уборку с `cleanup.py --id SIM-xxx --apply --docker`. Среда определяется профилем; если в нём задана команда `image_build` (например, FLYBOX), выполнить её перед испытанием. SIM-010 использует официальный образ Julia с закреплённым digest.

У SIM-011 отдельно проверяются Python-каскад и R-анализ; команда второго профиля и границы их результатов приведены в [порядке работы](docs/WORKFLOW.md). Каскад на отфильтрованном реальном графе не считается биофизической симуляцией всего коннектома.

SIM-013 запускается той же командой `simctl.py evaluate --id SIM-013`: профиль выбирает отдельный контроллер с depot Julia внутри временного Linux-контейнера. Windows bind используется для исходников, входов и результатов. После завершения контейнер вместе с Linux-кэшем удаляется; `--resume` для этого профиля неприменим. Неудачные попытки сохраняются отдельно.

Подробные логи, рабочие копии, веса и данные остаются в игнорируемой `research/.work/simulator-evaluation/<SIM>/<run>/`. В `artifacts/` публикуются зарегистрированные визуальные результаты с SHA-256 и описанием сценария. README каждого SIM явно показывает, если таких результатов ещё нет.
