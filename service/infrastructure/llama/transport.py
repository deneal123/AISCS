"""Фиксированный loopback-транспорт к llama-server без proxy, retries и внешних URL."""

import json
import urllib.error
import urllib.request

from ...domain.protocol.contracts import ProtocolFailure

MAX_BYTES = 1048576


class LlamaTransport:
    def __init__(self, key):
        self.key = key

    def __call__(self, path, body=None):
        headers = {"Authorization": "Bearer " + self.key}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            "http://127.0.0.1:8081" + path,
            data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            if body is not None
            else None,
            headers=headers,
        )
        try:
            # Не использовать proxy env даже для loopback child.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=120) as response:
                content = response.read(MAX_BYTES + 1)
                if len(content) > MAX_BYTES:
                    raise ProtocolFailure("upstream_output_limit", 502)
                return json.loads(content)
        except urllib.error.HTTPError as error:
            code = "context_or_request_rejected" if error.code == 400 else "upstream_unavailable"
            raise ProtocolFailure(code, 400 if error.code == 400 else 503) from None
        except ProtocolFailure:
            raise
        except Exception:
            raise ProtocolFailure("upstream_unavailable", 503) from None
