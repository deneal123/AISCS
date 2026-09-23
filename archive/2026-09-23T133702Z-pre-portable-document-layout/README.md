# Publications sidecar

Автономный контур подготовки статей и тезисов диссертации. Поданная статья МИН-2026
зарегистрирована как неизменяемая `PUB-001`; её название, статус и файлы защищены SHA-256.
Посторонние публикации сохранены только в `examples/legacy/` и не входят в рабочий реестр.

```powershell
uv sync --extra dev
uv run --frozen pubctl status
uv run --frozen pubctl validate
uv run --frozen pubctl list
uv run --frozen pubctl new PUB-002 article-slug "Рабочее название" --kind paper
uv run --frozen pubctl build PUB-TEMPLATE-001 --profile draft
```

`build/` содержит производные локальные файлы. Утверждённые версии создаются только
командой `release ... --apply` после release gate. Доказательства импортируются из
`research` в локальный snapshot; сборка не читает соседний каталог.

MCP: `aspa-publications`, entrypoint `publications-mcp`. Мутации требуют `apply=true`,
а изменение любого пути внутри `PUB-001` отклоняется независимо от флага.
Реестр проверяется по `data/document-registry.schema.json`; MCP также публикует registry,
outline, research snapshot, контекст документа и последний validation report.
