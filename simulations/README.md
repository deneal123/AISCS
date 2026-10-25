# Испытания симуляторов

Здесь сравниваются 32 закреплённых репозитория для будущего генератора данных. Установка, функциональный запуск и научная достоверность учитываются отдельно. Выбор реализации генератора остаётся открытым.

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
| `scripts/`, `environments/`, `tests/` | Инструменты, определения окружений и их проверки |
| `sidecars/` | Закреплённые исходники сабмодулей |

Команды из корня суперпроекта:

```powershell
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/simctl.py preflight
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/cleanup.py --apply --docker
docker build -t aspa-sim-flybox-node22-python:20261025 -f simulations/environments/flybox-node-python.Dockerfile simulations/environments
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/simctl.py evaluate --id SIM-009 --no-memory-limit
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/publish_artifacts.py
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/report.py
research/.venv/Scripts/python.exe -B -X utf8 simulations/scripts/check.py
```

После завершения SIM повторить уборку с `cleanup.py --id SIM-xxx --apply --docker`. Команда сборки образа в примере относится к FLYBOX; для остальных проектов используется среда их профиля.

Подробные логи, рабочие копии, веса и данные остаются в игнорируемой `research/.work/simulator-evaluation/<SIM>/<run>/`. В `artifacts/` публикуются зарегистрированные визуальные результаты с SHA-256 и описанием сценария. README каждого SIM явно показывает, если таких результатов ещё нет.
