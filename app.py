#!/usr/bin/env python3
"""Тонкая HTTP-обёртка: документ → markdown для LLM.

Без веб-фреймворка (stdlib + opendataloader_pdf + openpyxl) — на каждый запрос:
  POST /parse?filename=<name>   body = сырые байты документа
    → {"markdown": "...", "engine": "...", "chars": N, "duration_sec": <float>}
  GET /formats → {"formats": [...]}
  GET /health  → {"status": "ok", "formats": [...]}

Два маршрута, потому что документы и таблицы — принципиально разные вещи:

1. ДОКУМЕНТЫ (pdf/docx/pptx/rtf/html) — свёрстанные страницы. Их парсит
   opendataloader (Java): он читает вёрстку ВИЗУАЛЬНО и по линиям разметки
   восстанавливает таблицы, заголовки, списки. Не-PDF сначала доводим до PDF
   через LibreOffice headless.

2. ТАБЛИЦЫ (xlsx/xls/ods) — уже структурированные данные, и гнать их через
   PDF-рендер ЛОМАЕТ их: LibreOffice при экспорте Calc в PDF не печатает сетку,
   а без линий opendataloader не видит таблицу и склеивает всё в один абзац;
   вдобавок широкую таблицу PDF режет по страницам. Поэтому читаем ячейки
   напрямую (openpyxl) — распознавать то, что и так структурировано, незачем.
   .xls/.ods сначала конвертируем в .xlsx (LibreOffice умеет это хорошо).
"""

import json
import os
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import opendataloader_pdf
from openpyxl import load_workbook

PORT = int(os.environ.get("PORT", "8080"))
MAX_BYTES = int(os.environ.get("ODL_MAX_BYTES", str(20 * 1024 * 1024)))
LO_TIMEOUT = int(os.environ.get("ODL_LO_TIMEOUT_SEC", "120"))
PARSE_TIMEOUT = int(os.environ.get("ODL_PARSE_TIMEOUT_SEC", "300"))
SOFFICE = os.environ.get("ODL_SOFFICE", "soffice")
# Потолок на лист: гигантская выгрузка не должна раздуть контекст (бэкенд её потом
# всё равно сожмёт, но незачем гонять мегабайты по сети).
MAX_SHEET_ROWS = int(os.environ.get("ODL_MAX_SHEET_ROWS", "2000"))

# Таблицы — читаем ячейки напрямую (см. docstring).
SPREADSHEET_EXTENSIONS = (".xlsx", ".xls", ".ods")
# Свёрстанные документы — через LibreOffice → PDF → opendataloader. Текстовые форматы
# (txt/md/csv/json/код) сюда НЕ входят: бэкенд читает их сам.
DOCUMENT_EXTENSIONS = (
    ".docx", ".doc", ".odt", ".rtf",
    ".pptx", ".ppt", ".odp",
    ".html", ".htm",
)
SUPPORTED_EXTENSIONS = (".pdf", *DOCUMENT_EXTENSIONS, *SPREADSHEET_EXTENSIONS)


def extension_of(filename):
    return Path(str(filename or "")).suffix.lower()


def soffice_convert(src, workdir, target):
    """LibreOffice headless: конвертация в target ("pdf"/"xlsx"). → путь к результату."""
    # UserInstallation в temp: без своего профиля soffice падает в контейнере,
    # а параллельные запросы дерутся за общий профиль.
    profile = Path(workdir) / "lo-profile"
    out_dir = Path(workdir) / f"lo-{target}"
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            SOFFICE,
            f"-env:UserInstallation=file://{profile}",
            "--headless",
            "--norestore",
            "--convert-to",
            target,
            "--outdir",
            str(out_dir),
            str(src),
        ],
        capture_output=True,
        timeout=LO_TIMEOUT,
    )
    produced = sorted(out_dir.glob(f"*.{target}"))
    if not produced:
        detail = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
        raise RuntimeError(f"libreoffice produced no {target}: {detail}")
    return produced[0]


def _cell(value):
    if value is None:
        return ""
    # Трубы сломали бы разметку markdown-таблицы.
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def spreadsheet_to_markdown(src, workdir, ext):
    """xlsx/xls/ods → markdown-таблицы по листам, напрямую из ячеек."""
    if ext != ".xlsx":
        src = soffice_convert(src, workdir, "xlsx")

    # data_only=True → кэшированные значения формул вместо самих формул: LLM нужны числа.
    wb = load_workbook(src, data_only=True, read_only=True)
    blocks = []
    for sheet in wb.worksheets:
        rows = []
        for row in sheet.iter_rows(values_only=True):
            cells = [_cell(v) for v in row]
            if any(cells):  # пустые строки-разделители не тащим
                rows.append(cells)
            if len(rows) >= MAX_SHEET_ROWS:
                rows.append([f"…лист обрезан на {MAX_SHEET_ROWS} строках"])
                break
        if not rows:
            continue

        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        header, body = rows[0], rows[1:]
        lines = [
            f"## Лист: {sheet.title}",
            "",
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        lines += ["| " + " | ".join(r) + " |" for r in body]
        blocks.append("\n".join(lines))
    wb.close()

    if not blocks:
        raise RuntimeError("spreadsheet has no data")
    return "\n\n".join(blocks)


def pdf_to_markdown(pdf_path, workdir):
    """opendataloader-pdf: PDF → markdown. Каждый вызов поднимает JVM."""
    out_dir = Path(workdir) / "md"
    out_dir.mkdir(parents=True, exist_ok=True)
    opendataloader_pdf.convert(
        input_path=[str(pdf_path)],
        output_dir=str(out_dir),
        format="markdown",
    )
    produced = sorted(out_dir.rglob("*.md"))
    if not produced:
        raise RuntimeError("opendataloader produced no markdown")
    return "\n\n".join(p.read_text(encoding="utf-8", errors="replace") for p in produced)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._json(200, {"status": "ok", "formats": list(SUPPORTED_EXTENSIONS)})
        if path == "/formats":
            return self._json(200, {"formats": list(SUPPORTED_EXTENSIONS)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/parse":
            return self._json(404, {"error": "not found"})

        query = parse_qs(parsed.query)
        filename = (query.get("filename", [""])[0] or "").strip()
        ext = extension_of(filename)
        if ext not in SUPPORTED_EXTENSIONS:
            return self._json(415, {"error": f"unsupported format: {ext or 'unknown'}"})

        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return self._json(400, {"error": "empty body"})
        if length > MAX_BYTES:
            return self._json(413, {"error": "document too large"})
        raw = self.rfile.read(length)

        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as workdir:
                src = Path(workdir) / f"input{ext}"
                src.write_bytes(raw)

                if ext in SPREADSHEET_EXTENSIONS:
                    markdown = spreadsheet_to_markdown(src, workdir, ext)
                    engine = "openpyxl" if ext == ".xlsx" else "libreoffice+openpyxl"
                else:
                    if ext == ".pdf":
                        pdf_path, engine = src, "opendataloader"
                    else:
                        pdf_path = soffice_convert(src, workdir, "pdf")
                        engine = "libreoffice+opendataloader"
                    markdown = pdf_to_markdown(pdf_path, workdir)

            return self._json(
                200,
                {
                    "markdown": markdown,
                    "engine": engine,
                    "chars": len(markdown),
                    "duration_sec": round(time.monotonic() - started, 2),
                },
            )
        except subprocess.TimeoutExpired:
            return self._json(504, {"error": "conversion timeout"})
        except Exception as exc:  # defensive: бэкенд трактует любую ошибку как «нет результата»
            return self._json(500, {"error": "parse failed", "detail": str(exc)[-400:]})

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    print(
        f"opendataloader-sidecar on :{PORT} | max_bytes={MAX_BYTES} "
        f"| formats={len(SUPPORTED_EXTENSIONS)}",
        flush=True,
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
