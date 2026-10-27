"""Operational certification prints closed reasons, never foreign diagnostics."""

import asyncio
import runpy
import sys

import httpx
import pytest

from service.domain.client.protocol.failures import classify_provider_failure
from service.presentation.cli.gigachat.support import GigaChatSmokeFailure, bounded_failure_code

MARKER = "private-provider-body:https://private.invalid/?credential=secret"


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (MARKER, "remote"),
        (" timeout ", "timeout"),
        ("TIMEOUT", "timeout"),
        ("", "remote"),
        ("a" * 10000, "remote"),
    ],
    ids=["private_body", "normalized_timeout", "uppercase_timeout", "empty", "oversized"],
)
def test_untrusted_explicit_reason_is_never_projected(reason, expected):
    error = RuntimeError(MARKER)
    error.reason_code = reason
    assert bounded_failure_code(error) == expected


def test_typed_smoke_failure_sanitizes_unknown_reason_at_construction():
    error = GigaChatSmokeFailure(MARKER)
    assert error.reason_code == "smoke_failed"
    assert str(error) == "smoke_failed"


class PrivateObject:
    def __str__(self):
        raise AssertionError("private reason must not be stringified")

    def __bool__(self):
        raise AssertionError("private reason must not be coerced")


def test_unknown_reason_object_does_not_execute_conversion_hooks():
    error = RuntimeError(MARKER)
    error.reason_code = PrivateObject()
    assert bounded_failure_code(error) == "remote"
    assert classify_provider_failure(error).code.value == "remote"
    assert GigaChatSmokeFailure(PrivateObject()).reason_code == "smoke_failed"


@pytest.mark.parametrize("name", ["reason_code", "status_code", "response"])
def test_unknown_exception_property_cannot_break_failure_boundary(name):
    class BrokenProperty(RuntimeError):
        @property
        def reason_code(self):
            if name == "reason_code":
                raise ValueError(MARKER)
            return None

        @property
        def status_code(self):
            if name == "status_code":
                raise ValueError(MARKER)
            return None

        @property
        def response(self):
            if name == "response":
                raise ValueError(MARKER)
            return None

    assert bounded_failure_code(BrokenProperty(MARKER)) == "remote"
    assert classify_provider_failure(BrokenProperty(MARKER)).code.value == "remote"


@pytest.mark.parametrize("code", ["timeout", "auth", "no_compatible_model", "usage_missing"])
def test_closed_smoke_reason_survives(code):
    assert bounded_failure_code(GigaChatSmokeFailure(code)) == code


def test_unknown_explicit_reason_preserves_real_http_taxonomy():
    error = RuntimeError(MARKER)
    error.reason_code = MARKER
    error.status_code = 429
    assert bounded_failure_code(error) == "rate_limit"


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "auth"), (429, "rate_limit"), (503, "remote"), (202, "validation_failed")],
)
@pytest.mark.asyncio
async def test_remote_function_validation_keeps_http_taxonomy_without_body(
    monkeypatch, status, expected
):
    from service.presentation.cli.gigachat import tools as tools

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return httpx.Response(
                status, text=MARKER, request=httpx.Request("POST", "https://private.invalid")
            )

    monkeypatch.setattr(tools.gigachat, "_make_http_client", Client)
    with pytest.raises(Exception) as caught:
        await tools._validate([{"name": "static_tool"}])
    assert bounded_failure_code(caught.value) == expected


@pytest.mark.parametrize(
    "module",
    [
        "document_authoring_smoke",
        "gigachat.tools",
        "gigachat.workspace",
        "gigachat.qualification",
    ],
)
def test_cli_serialization_of_foreign_failure_is_bounded(monkeypatch, capsys, module):
    error = RuntimeError(MARKER)
    error.reason_code = MARKER

    def fail(coroutine):
        coroutine.close()
        raise error

    monkeypatch.setattr(asyncio, "run", fail)
    # A real `python -m` entrypoint starts without its target preloaded. Other
    # tests import these modules for helpers; retain them after this test, but
    # do not manufacture runpy's duplicate-module warning as runtime evidence.
    monkeypatch.delitem(sys.modules, "service.presentation.cli." + module, raising=False)
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("service.presentation.cli." + module, run_name="__main__")
    assert caught.value.code == 1
    output = capsys.readouterr()
    assert "FAILED code=remote" in output.out
    assert MARKER not in output.out + output.err
