from copy import deepcopy

import pytest

from service.services.simulations.manifest import REQUIRED_FILES, InvalidManifest, validate_manifest


def example():
    return {
        "configuration_sha256": "a" * 64,
        "contract_version": "1.0",
        "units": {"time": "ms", "signal": "uV", "current": "nA", "position": "um"},
        "versions": dict.fromkeys(("NEURON", "LFPy", "lfpykit", "numpy"), "test-version"),
        "files": [
            {"name": name, "bytes": 1, "sha256": "b" * 64} for name in sorted(REQUIRED_FILES)
        ],
        "metrics": {"samples": 4001},
    }


def test_complete_manifest_and_independent_time_grid():
    manifest = example()
    validate_manifest(manifest, {"duration_ms": 100, "dt_ms": 0.025}, "a" * 64)
    manifest["metrics"]["samples"] = 8001
    with pytest.raises(InvalidManifest, match="time_grid"):
        validate_manifest(manifest, {"duration_ms": 100, "dt_ms": 0.025}, "a" * 64)


@pytest.mark.parametrize("change", ["duplicate", "missing", "bool_size", "bad_hash", "bad_units"])
def test_incomplete_or_misrepresented_artifacts_are_never_publishable(change):
    manifest = deepcopy(example())
    if change == "duplicate":
        manifest["files"].append(manifest["files"][0])
    elif change == "missing":
        manifest["files"] = manifest["files"][:-1]
    elif change == "bool_size":
        manifest["files"][0]["bytes"] = True
    elif change == "bad_hash":
        manifest["files"][0]["sha256"] = "unknown"
    else:
        manifest["units"]["signal"] = "mV"
    with pytest.raises(InvalidManifest):
        validate_manifest(manifest, {"duration_ms": 100, "dt_ms": 0.025}, "a" * 64)


def test_whole_cns_cannot_publish_a_local_only_manifest_or_wrong_dataset():
    manifest = example()
    configuration = {"duration_ms": 100, "dt_ms": 0.025, "model_id": "male-cns-hybrid-v1"}
    with pytest.raises(InvalidManifest, match="incomplete_connectome"):
        validate_manifest(manifest, configuration, "a" * 64)
    for name in (
        "connectome.bin",
        "connectome.json",
        "connectome-states.npz",
        "connectome-spikes.parquet",
    ):
        manifest["files"].append({"name": name, "bytes": 1, "sha256": "c" * 64})
    manifest["connectome"] = {
        "dataset_id": "male-cns:v1.0-annotated-nonglial",
        "neurons": 166700,
        "edges": 25582938,
        "manifest_sha256": "742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2",
    }
    validate_manifest(manifest, configuration, "a" * 64)
    manifest["connectome"]["neurons"] = 6
    with pytest.raises(InvalidManifest, match="connectome_identity"):
        validate_manifest(manifest, configuration, "a" * 64)
    for malformed in (None, [], "unknown"):
        manifest["connectome"] = malformed
        with pytest.raises(InvalidManifest, match="connectome_identity"):
            validate_manifest(manifest, configuration, "a" * 64)
