"""HTTP-транспорт платной приёмки: сериализованный бюджет, без повторов и сырых логов."""

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx


class PaidGuard:
    def __init__(self, *, key, pricing, profile, ceiling=500):
        self.key, self.pricing, self.profile = key, pricing, profile
        self.ceiling = ceiling
        self.used = 0
        self.unknown = 0
        self.calls = []
        self.lock = threading.Lock()

    def forward(self, path, payload):
        kind = "embedding" if path == "/v1/embeddings" else "chat"
        expected = "gpthub-memory-embedding" if kind == "embedding" else "gpthub-memory"
        explicit = {m["provider"] + ":" + m["model"] for m in self.profile[kind]}
        if payload.get("model") not in {expected, *explicit} or payload.get("stream"):
            return 422, {}
        output = int(payload.get("max_tokens") or 0)
        if kind == "chat" and not 0 < output <= 512:
            return 422, {}
        prompt = len(json.dumps(payload, ensure_ascii=False).encode()) + 256
        if prompt > 20000:
            return 422, {}
        quotes = [
            self.pricing.price([{**model, "prompt": prompt, "completion": output}]).credits
            for model in self.profile[kind]
        ]
        if not quotes:
            return 503, {}
        ceiling = max(quotes)
        with self.lock:
            if self.used + ceiling > self.ceiling:
                return 402, {"error": {"message": "acceptance_budget_exhausted"}}
            self.used += ceiling
            try:
                with httpx.Client(timeout=40) as client:
                    response = client.post(
                        "http://agents:8090" + path,
                        json=payload,
                        headers={"Authorization": "Bearer " + self.key},
                    )
                response.raise_for_status()
                data = response.json()
                usage = data["usage"]
                calls = usage.get("calls")
                if not calls:
                    provider, _, model = data["model"].partition(":")
                    if not model and payload["model"] in explicit:
                        provider, _, model = payload["model"].partition(":")
                        if data["model"] != model:
                            raise ValueError("unexpected_model")
                    calls = [
                        {
                            "provider": provider,
                            "model": model,
                            "prompt": usage["prompt_tokens"],
                            "completion": 0,
                            "receipt_id": uuid4().hex,
                        }
                    ]
                allowed = {(m["provider"], m["model"]) for m in self.profile[kind]}
                if any((c["provider"], c["model"]) not in allowed for c in calls):
                    raise ValueError("unexpected_model")
                actual = self.pricing.price(calls).credits
                if actual > ceiling:
                    raise ValueError("quote_bound_exceeded")
            except Exception:
                self.unknown += ceiling
                return 502, {"error": {"message": "acceptance_call_unconfirmed"}}
            self.used -= ceiling - actual
            self.calls.extend(calls)
            return 200, data

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                authorization = self.headers.get("Authorization", "")
                if not hmac.compare_digest(authorization, "Bearer " + owner.key):
                    self.send_error(401)
                    return
                if self.path not in ("/v1/embeddings", "/v1/chat/completions"):
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 25000:
                    self.send_error(413)
                    return
                status, data = owner.forward(self.path, json.loads(self.rfile.read(length)))
                wire = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(wire)))
                self.end_headers()
                self.wfile.write(wire)

        server = ThreadingHTTPServer(("0.0.0.0", 18096), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
