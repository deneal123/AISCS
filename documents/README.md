# Рабочие публикации

Каждая новая публикация располагается целиком в `documents/<PUB-ID>/`. Открывайте её
`main.tex`; перенос всей папки публикации не требует файлов из sidecar.

- `PUB-001` — уже поданная неизменяемая версия: `../conference/neiro-miet/ru/`.
- `_templates/` — переносимые шаблоны статьи, тезисов и supplementary materials.

Новый каталог создаётся командой `pubctl new PUB-NNN slug "Название" --kind paper --apply`.
