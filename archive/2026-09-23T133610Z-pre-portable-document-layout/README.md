# Dissertation text sidecar

Автономный модульный LaTeX-контур текста диссертации. Магистерская работа AgentsSwarm
сохранена как пример в `examples/masters-agentswarm/` и не участвует в сборке.

```powershell
uv sync --extra dev
uv run --frozen textctl validate
uv run --frozen textctl build TEXT-001 --profile draft
```

Сборка использует явный конвейер XeLaTeX/Biber. Draft имеет временный внутренний
титульный лист и не запускает Biber; release запускает XeLaTeX → Biber → XeLaTeX × 2.
Release запрещён при `\ResultPending`, `\Blocked`, неизвестных evidence refs или
неутверждённых реквизитах. Реестр проверяется по `data/document-registry.schema.json`.
MCP: `aspa-text`, entrypoint `text-mcp`; все записи требуют явного `apply=true`.
