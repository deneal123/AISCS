import hashlib
import json
import zipfile

import numpy as np
import pytest

pytest.importorskip("neuron")

from service.application.replay.rerecord_preview import rerecord_preview  # noqa: E402
from service.infrastructure.stimulation.current_archive import (  # noqa: E402
    rerecord_current_archive,
    write_current_archive,
)
from service.infrastructure.stimulation.current_transport import (  # noqa: E402
    pack_current_archive,
    unpack_current_archive,
)
from tests.test_network_recording import pair  # noqa: E402


def test_transport_roundtrip_retains_recording_and_detects_changes(tmp_path):
    e1, ref = [0, 200, 0], [200, 200, 0]
    source, package, restored = (
        tmp_path / "source",
        tmp_path / "currents.zip",
        tmp_path / "restored",
    )
    digest = write_current_archive([pair(1), pair(2, 1250)], source, e1, ref)
    info = pack_current_archive(source, digest, package)
    assert info["bytes"] == package.stat().st_size
    unpack_current_archive(package, info["sha256"], digest, restored)
    first = rerecord_current_archive(source, digest, e1, ref)
    second = rerecord_current_archive(restored, digest, e1, ref)
    np.testing.assert_array_equal(first["total_uv"], second["total_uv"])
    assert first["cells"] == second["cells"] == 2
    with pytest.raises(FileExistsError):
        pack_current_archive(source, digest, package)
    raw = package.read_bytes()
    package.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ValueError, match="package checksum"):
        unpack_current_archive(package, info["sha256"], digest, tmp_path / "corrupt")


def test_transport_refuses_unexpected_paths_and_missing_members(tmp_path):
    e1, ref = [0, 200, 0], [200, 200, 0]
    source, package = tmp_path / "source", tmp_path / "malicious.zip"
    digest = write_current_archive([pair(1)], source, e1, ref)
    with zipfile.ZipFile(package, "w", zipfile.ZIP_STORED) as out:
        out.writestr("manifest.json", (source / "manifest.json").read_bytes())
        out.writestr("../escape.npz", (source / "cell-000000.npz").read_bytes())
    package_digest = hashlib.sha256(package.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Unexpected"):
        unpack_current_archive(package, package_digest, digest, tmp_path / "destination")
    assert not (tmp_path / "escape.npz").exists()
    assert not (tmp_path / "destination").exists()
    assert len(json.loads((source / "manifest.json").read_text())["cells"]) == 1


def test_rerecord_preview_changes_contact_and_cleans_temporary_data(tmp_path):
    e1, ref = [0, 200, 0], [200, 200, 0]
    source, package = tmp_path / "source", tmp_path / "currents.zip"
    digest = write_current_archive([pair(1), pair(2, 1250)], source, e1, ref)
    info = pack_current_archive(source, digest, package)
    workspace = tmp_path / "work"
    first = rerecord_preview(package, info["sha256"], digest, workspace, e1, ref)
    swapped = rerecord_preview(package, info["sha256"], digest, workspace, ref, e1)
    assert first["cells"] == 2
    assert first["time_ms"] == swapped["time_ms"]
    np.testing.assert_allclose(first["total_uv"], -np.asarray(swapped["total_uv"]), atol=1e-12)
    filtered = rerecord_preview(
        package, info["sha256"], digest, workspace, e1, ref,
        acquisition={"low_hz": 100, "high_hz": 3000, "recovery_ms": 0.5, "clip_uv": 1},
    )
    assert len(filtered["acquisition"]["valid_samples"]) == filtered["shown_samples"]
    intervals = filtered["acquisition"]["mask_intervals"]
    assert intervals[0]["start_ms"] == filtered["time_ms"][0]
    assert intervals[-1]["end_ms"] == filtered["time_ms"][-1]
    assert all(a["end_ms"] == b["start_ms"] for a, b in zip(intervals, intervals[1:], strict=False))
    assert any(not valid for valid in filtered["acquisition"]["valid_samples"])
    assert filtered["shown_samples"] <= 4096
    assert not list(workspace.iterdir())
    with pytest.raises(ValueError, match="checksum"):
        rerecord_preview(package, "0" * 64, digest, workspace, e1, ref)
    assert not list(workspace.iterdir())
