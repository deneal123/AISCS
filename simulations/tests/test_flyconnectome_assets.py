"""A verified public metadata receipt cannot silently change release identity."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inventory
import simctl
from probes import flyconnectome_assets


@pytest.mark.parametrize("change", ["receipt", "metadata"])
def test_metadata_change_is_rejected_and_never_overwritten(
    tmp_path, monkeypatch, change
):
    work = tmp_path / "work"
    assets = work / "SIM-026/assets"
    assets.mkdir(parents=True)
    payload = b'{"data_type":"uint64"}'
    metadata = assets / "segmentation-v630-info.json"
    for name in flyconnectome_assets.ROUTES:
        (assets / (name + "-info.json")).write_bytes(payload)
    receipt = assets / "route-check.json"
    receipt.write_text(
        json.dumps(
            {
                "routes": {
                    name: {
                        "status": "available",
                        "file": name + "-info.json",
                        "url": url,
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                    for name, url in flyconnectome_assets.ROUTES.items()
                }
            }
        )
    )
    row = {
        "id": "SIM-026",
        "commit": flyconnectome_assets.COMMIT,
        "access_preflight": {
            "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()
        },
    }
    monkeypatch.setattr(simctl, "WORK", work)
    monkeypatch.setattr(inventory, "WORK", work)
    monkeypatch.setattr(flyconnectome_assets, "WORK", work)
    original_load = flyconnectome_assets.load
    monkeypatch.setattr(
        flyconnectome_assets,
        "load",
        lambda path: (
            {"candidates": [row]}
            if path == flyconnectome_assets.REGISTRY
            else original_load(path)
        ),
    )
    if change == "receipt":
        receipt.write_text('{"routes":{}}')
    else:
        metadata.write_bytes(b'{"data_type":"float32"}')
    run = work / "SIM-026/20261026T000000Z-check"
    run.mkdir(parents=True)
    with pytest.raises(ValueError, match="changed"):
        flyconnectome_assets.hydrate(run)
    assert metadata.read_bytes() == (
        b'{"data_type":"float32"}'
        if change == "metadata"
        else b'{"data_type":"uint64"}'
    )


def test_hydration_cannot_target_another_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    monkeypatch.setattr(flyconnectome_assets, "WORK", tmp_path)
    with pytest.raises(ValueError, match="owned SIM-026"):
        flyconnectome_assets.hydrate(tmp_path / "SIM-025/20261026T000000Z-check")


def test_metadata_retry_budget_survives_new_invocation(tmp_path, monkeypatch):

    monkeypatch.setattr(inventory, "WORK", tmp_path)
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    attempts = []

    def unavailable(url, **kwargs):
        attempts.append(url)
        raise OSError("Fixture metadata route unavailable")

    monkeypatch.setattr(flyconnectome_assets.urllib.request, "urlopen", unavailable)
    routes = {
        name: {
            "url": url,
            "file": name + "-info.json",
            "bytes": 2,
            "sha256": hashlib.sha256(b"{}").hexdigest(),
        }
        for name, url in flyconnectome_assets.ROUTES.items()
    }
    for _ in range(2):
        with pytest.raises(ValueError, match="two attempts"):
            flyconnectome_assets.acquire_metadata(tmp_path, routes)
    assert len(attempts) == 2


def test_cached_metadata_receipt_resolves_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(inventory, "WORK", tmp_path)
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    monkeypatch.setattr(flyconnectome_assets, "ROOT", tmp_path)
    routes = {
        name: {
            "url": url,
            "file": name + "-info.json",
            "bytes": 2,
            "sha256": hashlib.sha256(b"{}").hexdigest(),
        }
        for name, url in flyconnectome_assets.ROUTES.items()
    }
    for item in routes.values():
        (tmp_path / item["file"]).write_bytes(b"{}")
    monkeypatch.setattr(
        flyconnectome_assets.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail(
            "Verified cache must not request the network"
        ),
    )
    result = flyconnectome_assets.acquire_metadata(tmp_path, routes)
    receipt = tmp_path / result["requests"]
    assert receipt.is_file() and json.loads(receipt.read_text()) == {}
