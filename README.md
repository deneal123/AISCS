# opendataloader — сайдкар парсинга документов

Превращает вложение пользователя в **markdown, пригодный для LLM**: заголовки, таблицы, списки.
Ветка-сабмодуль репозитория GPTHub (как `whisper`, `memos`, `ldr`).

## Что внутри

Два маршрута, потому что свёрстанный документ и электронная таблица — принципиально разные вещи.

**1. Документы** (`pdf`, `docx`, `doc`, `odt`, `rtf`, `pptx`, `ppt`, `odp`, `html`) →
[opendataloader-pdf](https://github.com/opendataloader-project/opendataloader-pdf) (Hancom, Apache-2.0).
Он читает вёрстку **визуально** и по линиям разметки восстанавливает таблицы, заголовки и списки.
Парсит только PDF, поэтому не-PDF сначала доводим до PDF через **LibreOffice headless**.

**2. Таблицы** (`xlsx`, `xls`, `ods`) → **openpyxl**, напрямую по ячейкам.
Через PDF их гнать нельзя: LibreOffice при экспорте Calc в PDF **не печатает сетку**, а без линий
opendataloader не видит таблицу и склеивает всё в один абзац; вдобавок широкую таблицу PDF режет по
страницам. Электронная таблица уже структурирована — распознавать её обратно незачем.
`.xls`/`.ods` сначала конвертируем в `.xlsx` (это LibreOffice умеет хорошо).

Исходники upstream здесь **не вендорятся** — пакет ставится из PyPI по пину (`OPENDATALOADER_VERSION`
в `Dockerfile`). Тот же приём, что в сабмодуле `whisper`, где whisper.cpp клонируется на этапе сборки.

## API

| Метод | Ответ |
|---|---|
| `GET /health` | `{"status": "ok", "formats": [...]}` |
| `GET /formats` | `{"formats": [".pdf", ".docx", ...]}` |
| `POST /parse?filename=<имя>` | тело = **сырые байты** документа (`application/octet-stream`) → `{"markdown", "engine", "chars", "duration_sec"}` |

`engine` — `opendataloader` для PDF или `libreoffice+opendataloader` для office-форматов.

Форматы: `pdf`, `docx`, `doc`, `odt`, `rtf`, `xlsx`, `xls`, `ods`, `pptx`, `ppt`, `odp`, `html`, `htm`.
Текстовые файлы (`txt`/`md`/`csv`/`json`/код) сюда не отдаём — бэкенд читает их напрямую.

## Переменные окружения

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `PORT` | `8080` | Порт HTTP |
| `ODL_MAX_BYTES` | `20971520` | Лимит тела (совпадает с гейтом аплоада в бэкенде) |
| `ODL_LO_TIMEOUT_SEC` | `120` | Таймаут конвертации LibreOffice |
| `ODL_PARSE_TIMEOUT_SEC` | `300` | Таймаут парсинга |

## Как это видит бэкенд

Клиент — `OpenDataLoaderParser` (`backend/service/services/chat/infrastructure/media/`), включается
флагом `AGENTS__OPENDATALOADER_ENABLED`. Работает **fail-open**: если сайдкар недоступен или вернул
ошибку, бэкенд молча падает на старый путь (PyPDF2/python-docx) — загрузка файлов не ломается.

## Локально

```bash
docker build -t odl-sidecar .
docker run --rm -p 8080:8080 odl-sidecar
curl -s --data-binary @doc.pdf "http://localhost:8080/parse?filename=doc.pdf" | jq -r .markdown
```

Первый вызов на контейнер медленнее: JVM и профиль LibreOffice поднимаются с нуля.
