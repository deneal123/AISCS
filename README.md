# Presentation sidecar

Рабочий документ целиком находится в `document/`; главный файл —
`document/presentation.tex`. Эту папку можно независимо перенести и собрать её собственным
`build.ps1`. Модульная Beamer-презентация предназначена для защиты диссертации. Пример магистерской презентации
сохранён в `examples/masters-agentswarm/` и не участвует в сборке.

```powershell
uv sync --extra dev
uv run --frozen presentationctl validate
uv run --frozen presentationctl build PRES-001 --profile draft
```

Draft допускает `\ResultPending`; release запрещает placeholders и требует approvals.
Реестр проверяется по `data/document-registry.schema.json`. MCP: `aspa-presentation`,
entrypoint `presentation-mcp`; все записи требуют явного `apply=true`.
