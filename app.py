#!/usr/bin/env python3
"""Тонкая HTTP-обёртка над opendataloader-pdf: документ → markdown для LLM.

Без веб-фреймворка (stdlib + сам opendataloader_pdf) — на каждый запрос:
  POST /parse?filename=<name>   body = сырые байты документа
    → office-формат? soffice --headless --convert-to pdf
    → opendataloader_pdf.convert(format="markdown")  (запускает java -jar)
    → {"markdown": "...", "engine": "...", "chars": N, "duration_sec": <float>}
  GET /formats → {"formats": [...]}
  GET /health  → {"status": "ok", "formats": [...]}

Ядро opendataloader парсит ТОЛЬКО PDF (структура, таблицы, заголовки). Office-форматы
доводим до PDF через LibreOffice headless — так один сервис закрывает docx/xlsx/pptx/rtf,
которые иначе пришлось бы тащить зоопарком python-библиотек с худшим качеством таблиц.
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

PORT = int(os.environ.get("PORT", "8080"))
MAX_BYTES = int(os.environ.get("ODL_MAX_BYTES", str(20 * 1024 * 1024)))
LO_TIMEOUT = int(os.environ.get("ODL_LO_TIMEOUT_SEC", "120"))
PARSE_TIMEOUT = int(os.environ.get("ODL_PARSE_TIMEOUT_SEC", "300"))
SOFFICE = os.environ.get("ODL_SOFFICE", "soffice")

# Расширения, которые LibreOffice умеет привести к PDF. Текстовые форматы
# (txt/md/csv/json/код) сюда НЕ входят: бэкенд читает их напрямую, гонять их
# через PDF было бы только потерей качества и времени.
OFFICE_EXTENSIONS = (
    ".docx", ".doc", ".odt", ".rtf",
    ".xlsx", ".xls", ".ods",
    ".pptx", ".ppt", ".odp",
    ".html", ".htm",
)
SUPPORTED_EXTENSIONS = (".pdf", *OFFICE_EXTENSIONS)


def extension_of(filename):
    return Path(str(filename or "")).suffix.lower()


def office_to_pdf(src, workdir):
    """LibreOffice headless: office-документ → PDF. Возвращает путь к PDF или None."""
    # UserInstallation в temp: без своего профиля soffice падает в контейнере,
    # а параллельные запросы дерутся за общий профиль.
    profile = Path(workdir) / "lo-profile"
    proc = subprocess.run(
        [
            SOFFICE,
            f"-env:UserInstallation=file://{profile}",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(workdir),
            str(src),
        ],
        capture_output=True,
        timeout=LO_TIMEOUT,
    )
    produced = sorted(Path(workdir).glob("*.pdf"))
    if not produced:
        detail = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
        raise RuntimeError(f"libreoffice produced no pdf: {detail}")
    return produced[0]


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

                if ext == ".pdf":
                    pdf_path, engine = src, "opendataloader"
                else:
                    pdf_path = office_to_pdf(src, workdir)
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
        f"opendataloader-sidecar on :{PORT} | max_bytes={MAX_BYTES} | formats={len(SUPPORTED_EXTENSIONS)}",
        flush=True,
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
