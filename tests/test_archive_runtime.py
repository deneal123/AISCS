"""Portable path contract; actual descriptor execution is tested on Linux."""

import pytest
from application import archive_runtime


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "a/../b", "a//b", "a\\b", "a/./b", "a\x00b"]
)
def test_unsafe_member_parts_are_rejected(name):
    assert archive_runtime.member_parts(name) is None


@pytest.mark.parametrize("name", ["main.tex", "content/part.tex", "figures/рисунок.png"])
def test_regular_members_are_supported(name):
    assert archive_runtime.member_parts(name) == name.split("/")


def test_unsupported_host_fails_closed_without_opening_anything(monkeypatch, capsys):
    monkeypatch.setattr(archive_runtime.os, "name", "nt")

    def forbidden(*args, **kwargs):
        raise AssertionError("unsupported host must not access filesystem")

    monkeypatch.setattr(archive_runtime.os, "open", forbidden)
    archive_runtime.main("source", "destination", "root", 400, 1024)
    assert capsys.readouterr().out == "__REFUSED__\n"
