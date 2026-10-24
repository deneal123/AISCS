"""Общий use case одного inference без HTTP, subprocess и скрытого повторного вызова."""

import threading
from contextlib import contextmanager

from ..domain.protocol.compiler import compile_request
from ..domain.protocol.contracts import ProtocolFailure
from ..domain.protocol.response import normalize_response


class InferenceService:
    def __init__(self, upstream):
        self.upstream = upstream
        self.slot = threading.BoundedSemaphore(1)

    @contextmanager
    def complete(self, body):
        request = compile_request(body)
        if not self.slot.acquire(blocking=False):
            raise ProtocolFailure("model_busy", 429)
        try:
            raw = self.upstream("/v1/chat/completions", request.body)
            yield request, normalize_response(raw, request)
        finally:
            self.slot.release()
