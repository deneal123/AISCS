"""Protect exact author input bytes and independent export decoding."""

import hashlib
import io
import struct
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probes.flyvis_assets import identity
from probes.flyvis_reader import read_array


def test_exact_blob_rejects_modified_input(tmp_path):
    path = tmp_path / "spec.json"
    data = b'{"upstream": true}\n'
    path.write_bytes(data)
    oid = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    assert identity(path, oid)["sha256"] == hashlib.sha256(data).hexdigest()
    path.write_bytes(data.replace(b"\n", b"\r\n"))
    with pytest.raises(ValueError, match="pinned Git input differs"):
        identity(path, oid)


def test_reader_decodes_exported_values_without_numpy():
    raw = struct.pack("<ff", 1.0, 2.5)
    header = b"{'descr': '<f4', 'fortran_order': False, 'shape': (1, 2)}\n"
    data = b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + raw
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("activity.npy", data)
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive:
        values, shape, digest = read_array(archive, "activity")
    assert list(values) == [1.0, 2.5] and shape == (1, 2)
    assert digest == hashlib.sha256(raw).hexdigest()
