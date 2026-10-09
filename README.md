# Презентация диссертационного исследования

11 слайдов о постановке исследования и плане работы по ИПР 2026–2030. Автор — Данил Федорович Вольхин. Основной исходник — [document/presentation.tex](document/presentation.tex), формат Beamer 4:3, Arial, белый фон и чёрный текст по предоставленному PPTX БТС-41-2024-Вольхин.

```powershell
uv sync --extra dev
uv run --frozen presentationctl validate
uv run --frozen presentationctl build PRES-001 --profile draft
```

Каталог [document/](document/README.md) можно перенести и собрать XeLaTeX отдельно. Презентация не содержит собственных экспериментальных результатов или заявлений о доказанной пользе переноса. Источники и внутренние привязки хранятся отдельно; на слайдах — обычные библиографические ссылки.

Успешная сборка через CLI/MCP обновляет [PDF для просмотра](document/presentation.pdf) рядом с исходником. Ошибка сборки, проверочный запуск и отказ выпуска сохраняют предыдущий PDF.

[Структура](docs/outline.md) · [Проверка оформления](docs/formatting-audit.md) · [TODO](TODO.md). CLI и MCP `aspa-presentation` сохранены; release требует согласований. Пример AgentsSwarm и прежние снимки не изменены.
