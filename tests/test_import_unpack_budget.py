"""Run the generated extraction script against bounded, real ZIP fixtures."""

import os
import shlex
import subprocess
import sys
import zipfile

import pytest
from application import importer

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Linux descriptor runtime")


def extract(tmp_path, monkeypatch, entries, budget=10):
    monkeypatch.setattr(importer, "MAX_UNPACKED_BYTES", budget)
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in entries:
            bundle.writestr(name, data)
    # The runtime command is POSIX; execute its exact script with Windows-native
    # fixture paths rather than interpreting the shell prefix on this host.
    args = shlex.split(importer.unpack_command("/workspace", "source.zip"))
    start = args.index("python3")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            args[start + 2],
            str(archive),
            str(tmp_path / "source"),
            str(tmp_path),
            "400",
            str(budget),
        ],
        capture_output=True,
        timeout=10,
        check=True,
    )
    return tmp_path / "source", result.stdout.decode()


@pytest.mark.parametrize("entries", [[("one.txt", b"x" * 11)], [("a", b"x" * 6), ("b", b"x" * 5)]])
def test_unpack_never_writes_beyond_aggregate_budget(tmp_path, monkeypatch, entries):
    output, report = extract(tmp_path, monkeypatch, entries)
    total = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    assert total <= 10
    assert "__TRUNCATED__" in report
    assert "__OK__" not in report


def test_unpack_accepts_exact_aggregate_budget(tmp_path, monkeypatch):
    output, report = extract(tmp_path, monkeypatch, [("a", b"x" * 6), ("b", b"y" * 4)])
    assert (output / "a").read_bytes() == b"x" * 6
    assert (output / "b").read_bytes() == b"y" * 4
    assert "__TRUNCATED__" not in report
    assert "__OK__ 2" in report


def test_unpack_preserves_preexisting_user_edit(tmp_path, monkeypatch):
    output = tmp_path / "source"
    output.mkdir()
    (output / "edited.txt").write_bytes(b"user edit")
    output, report = extract(tmp_path, monkeypatch, [("edited.txt", b"original"), ("new", b"ok")])
    assert (output / "edited.txt").read_bytes() == b"user edit"
    assert (output / "new").read_bytes() == b"ok"
    assert "__OK__" in report
