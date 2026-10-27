"""Приёмочный observer не раскрывает исключение и не меняет результат mapper."""

import json
from io import StringIO

from scripts.harness.live.worker_entry import exception_diagnostic, forward_diagnostics, install


def test_exception_chain_does_not_include_text_locals_or_external_paths():
    try:
        try:
            raise ValueError("PRIVATE_CAPABILITY")
        except ValueError as cause:
            raise TypeError("PRIVATE_REQUEST") from cause
    except TypeError as error:
        actual = exception_diagnostic(error)
    assert actual == {
        "stage": "worker_exception",
        "chain": [
            {"error": "TypeError", "frames": []},
            {"error": "ValueError", "frames": []},
        ],
    }
    assert "PRIVATE" not in json.dumps(actual)


def test_observer_passes_same_exception_and_kwargs_to_real_mapper(monkeypatch):
    from service.services.chat.application import error_handling

    seen, result = [], {"error_code": "unchanged"}

    def mapper(error, **kwargs):
        seen.append((error, kwargs))
        return result

    monkeypatch.setattr(error_handling, "map_to_worker_error_payload", mapper)
    install()
    output = StringIO()
    monkeypatch.setattr("sys.__stdout__", output)
    error = RuntimeError("PRIVATE_REQUEST")
    assert error_handling.map_to_worker_error_payload(error, job_id="not_printed") is result
    assert seen == [(error, {"job_id": "not_printed"})]
    assert json.loads(output.getvalue()) == exception_diagnostic(error)
    assert "PRIVATE" not in output.getvalue() and "not_printed" not in output.getvalue()


def test_forwarder_discards_worker_banner_and_arbitrary_logs(capsys):
    forward_diagnostics(
        StringIO('PRIVATE_LOG\n{"broker":"PRIVATE_URL"}\n{"stage":"worker_exception","chain":[]}\n')
    )
    assert json.loads(capsys.readouterr().out) == {"stage": "worker_exception", "chain": []}
