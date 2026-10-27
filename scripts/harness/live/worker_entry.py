"""Приёмочный worker: наблюдение исключений без текста, locals и изменения решений."""

import json
import sys
import traceback
from pathlib import Path

_ERRORS = frozenset(
    {
        "RuntimeError",
        "ValueError",
        "TypeError",
        "AttributeError",
        "KeyError",
        "HTTPException",
        "TimeoutError",
        "AssertionError",
        "ValidationError",
        "IntegrityError",
        "OperationalError",
        "InterfaceError",
        "ProgrammingError",
    }
)


def exception_diagnostic(error):
    chain, seen = [], set()
    while error is not None and id(error) not in seen and len(chain) < 3:
        seen.add(id(error))
        frames = []
        for frame in traceback.extract_tb(error.__traceback__)[-6:]:
            parts = Path(frame.filename).parts
            if "service" in parts:
                frames.append(
                    {
                        "source": "/".join(parts[parts.index("service") :]),
                        "function": frame.name,
                        "line": frame.lineno,
                    }
                )
        name = type(error).__name__
        chain.append({"error": name if name in _ERRORS else "internal", "frames": frames})
        error = error.__cause__ or error.__context__
    return {"stage": "worker_exception", "chain": chain}


def install():
    from service.services.chat.application import error_handling

    original = error_handling.map_to_worker_error_payload

    def observed(error, **kwargs):
        print(json.dumps(exception_diagnostic(error)), file=sys.__stdout__, flush=True)
        return original(error, **kwargs)

    error_handling.map_to_worker_error_payload = observed


def forward_diagnostics(stream):
    """Стандартный banner и сторонние логи worker не выходят в отчёт приёмки."""
    for line in stream:
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and value.get("stage") == "worker_exception":
            print(json.dumps(value), flush=True)


if __name__ == "__main__":
    install()
    from celery.__main__ import main

    main()
