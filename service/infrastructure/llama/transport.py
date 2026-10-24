"""Фиксированный loopback-транспорт к llama-server без proxy, retries и внешних URL."""

import json
import logging
import urllib.error
import urllib.request

from ...domain.protocol.contracts import ProtocolFailure

MAX_BYTES = 1048576
logger = logging.getLogger(__name__)


def failure_category(error):
    """Только закрытая категория; нативное тело может содержать пользовательский текст."""
    try:
        payload = json.loads(error.read(8192))
        message = str(payload.get("error", {}).get("message", "")).lower()
    except (ValueError, TypeError, AttributeError, OSError):
        return "unknown"
    for category, markers in (
        ("grammar", ("grammar", "schema")),
        (
            "tool_parse",
            (
                "tool call",
                "tool_call",
                "failed to parse",
                "does not match the expected",
                "invalid diff:",
            ),
        ),
        ("context_limit", ("context size", "context length", "context window")),
    ):
        if any(marker in message for marker in markers):
            return category
    return "unknown"


class LlamaTransport:
    def __init__(self, key, *, request_timeout=330.0):
        self.key = key
        # Шлюз получает шанс вернуть ответ до внешнего транспортного таймаута.
        self.timeout = request_timeout - min(5.0, request_timeout / 10.0)

    def __call__(self, path, body=None):
        operation = "chat" if path == "/v1/chat/completions" else "probe"
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
            with opener.open(request, timeout=self.timeout) as response:
                content = response.read(MAX_BYTES + 1)
                if len(content) > MAX_BYTES:
                    raise ProtocolFailure("upstream_output_limit", 502)
                return json.loads(content)
        except urllib.error.HTTPError as error:
            logger.warning(
                "local_llm_upstream_http_failure operation=%s status_code=%s category=%s",
                operation,
                error.code,
                failure_category(error),
            )
            code = "context_or_request_rejected" if error.code == 400 else "upstream_unavailable"
            raise ProtocolFailure(code, 400 if error.code == 400 else 503) from None
        except ProtocolFailure:
            raise
        except Exception as error:
            logger.warning(
                "local_llm_upstream_transport_failure operation=%s kind=%s",
                operation,
                type(error).__name__,
            )
            raise ProtocolFailure("upstream_unavailable", 503) from None
