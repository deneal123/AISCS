"""Ограниченный HTTP-транспорт к одному inference; здесь нет agent loop или tools executor."""

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..application.inference import InferenceService
from ..domain.protocol.contracts import ProtocolFailure
from ..domain.protocol.response import stream_events

MAX_BYTES = 1048576


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, key, *, upstream):
        self.key = key
        self.upstream = upstream
        self.connections = threading.BoundedSemaphore(8)
        self.completions = InferenceService(upstream)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()

    def handle_error(self, request, client_address):
        # Base class печатает traceback с данными соединения. Он не нужен для работы API.
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "GPTHubLocal/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        pass

    def send_json(self, status, value):
        content = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def fail(self, error):
        self.send_json(
            error.status,
            {
                "error": {
                    "type": "local_llm_error",
                    "code": error.code,
                    "message": error.code,
                }
            },
        )

    def send_error(self, code, message=None, explain=None):
        self.fail(ProtocolFailure("http_request_invalid", code))

    def authenticated(self):
        return hmac.compare_digest(
            self.headers.get("Authorization", "").encode(), ("Bearer " + self.server.key).encode()
        )

    def do_GET(self):
        try:
            if self.path == "/health":
                self.server.upstream("/health")
                return self.send_json(200, {"status": "ok"})
            if not self.authenticated():
                raise ProtocolFailure("unauthorized", 401)
            if self.path != "/v1/models":
                raise ProtocolFailure("not_found", 404)
            self.send_json(200, self.server.upstream(self.path))
        except ProtocolFailure as error:
            self.fail(error)
        except Exception:
            self.fail(ProtocolFailure("request_unavailable", 503))

    def do_POST(self):
        try:
            if not self.authenticated():
                raise ProtocolFailure("unauthorized", 401)
            if self.path != "/v1/chat/completions":
                raise ProtocolFailure("not_found", 404)
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                raise ProtocolFailure("request_framing_invalid")
            try:
                length = int(lengths[0])
            except ValueError:
                raise ProtocolFailure("request_framing_invalid") from None
            if not 0 < length <= MAX_BYTES:
                raise ProtocolFailure("request_limit", 413)
            content = self.rfile.read(length)
            if len(content) != length:
                raise ProtocolFailure("request_framing_invalid")
            try:
                body = json.loads(content)
            except ValueError:
                raise ProtocolFailure("request_invalid") from None
            with self.server.completions.complete(body) as (request, result):
                if not request.stream:
                    return self.send_json(200, result)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                for chunk in stream_events(result, include_usage=request.include_usage):
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except ProtocolFailure as error:
            self.fail(error)
        except Exception:
            self.fail(ProtocolFailure("request_unavailable", 503))
