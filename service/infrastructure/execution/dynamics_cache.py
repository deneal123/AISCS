"""Bounded, disposable numerical cache; backend remains the durable artifact owner."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

import numpy as np

from service.contracts import SimulationConfig
from service.domain.model import Dynamics
from service.domain.ports import NumericalEngine
from service.shared.json_io import write_json

ARRAYS = (
    "time_ms",
    "voltage_mv",
    "membrane_current_na",
    "starts_um",
    "ends_um",
    "diameters_um",
    "cell_ids",
)


def metadata_digest(info: dict) -> str:
    return hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()


class CachedDynamics:
    def __init__(self, engine: NumericalEngine, root: Path, identity: dict, max_bytes: int):
        self.engine, self.root = engine, root
        self.identity, self.max_bytes = identity, max_bytes

    def key(self, config: SimulationConfig) -> str:
        payload = {"engine": self.identity, "configuration": config.dynamics_digest()}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def load(self, config: SimulationConfig, key: str) -> Dynamics | None:
        data = self.root / (key + ".npz")
        metadata = self.root / (key + ".json")
        if not data.is_file() or not metadata.is_file():
            return None
        info = json.loads(metadata.read_text(encoding="utf-8"))
        expected_metadata = info.pop("metadata_sha256")
        if (
            metadata_digest(info) != expected_metadata
            or info["key"] != key
            or info["engine"] != self.identity
            or data.stat().st_size > self.max_bytes
            or hashlib.sha256(data.read_bytes()).hexdigest() != info["data_sha256"]
        ):
            raise ValueError("Cache integrity mismatch")
        with np.load(data, allow_pickle=False) as archive:
            arrays = {name: archive[name].copy() for name in ARRAYS}
            connectome_arrays = {
                name[4:]: archive[name].copy() for name in archive.files if name.startswith("cns_")
            }
        segments = len(arrays["cell_ids"])
        samples = round(config.duration_ms / config.dt_ms) + 1
        if (
            arrays["voltage_mv"].shape != (segments, samples)
            or arrays["membrane_current_na"].shape != (segments, samples)
            or arrays["starts_um"].shape != (segments, 3)
            or arrays["ends_um"].shape != (segments, 3)
            or arrays["diameters_um"].shape != (segments,)
            or arrays["time_ms"].shape != (samples,)
            or not all(np.isfinite(value).all() for value in arrays.values())
            or not np.allclose(np.diff(arrays["time_ms"]), config.dt_ms, atol=1e-7)
        ):
            raise ValueError("Cache scientific state mismatch")
        data.touch()
        return Dynamics(
            **arrays,
            soma_segment_ids=info["soma_segment_ids"],
            spikes=info["spikes"],
            input_events=info["input_events"],
            connectome={"arrays": connectome_arrays, "metadata": info["connectome"]}
            if info.get("connectome")
            else None,
            seconds=0.0,
            cache_info={
                "status": "hit",
                "key": key,
                "engine": self.identity,
                "data_sha256": info["data_sha256"],
                "original_solver_seconds": info["solver_seconds"],
            },
        )

    def store(self, dynamics: Dynamics, key: str) -> dict:
        nonce = uuid4().hex
        temporary = self.root / f".{key}.{nonce}.npz"
        pending = self.root / f".{key}.{nonce}.json"
        try:
            extras = {
                "cns_" + name: value
                for name, value in (dynamics.connectome or {}).get("arrays", {}).items()
            }
            np.savez_compressed(
                temporary, **{name: getattr(dynamics, name) for name in ARRAYS}, **extras
            )
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            if temporary.stat().st_size > self.max_bytes:
                return {"status": "miss_oversized", "key": key, "engine": self.identity}
            metadata = {
                "key": key,
                "engine": self.identity,
                "data_sha256": digest,
                "soma_segment_ids": dynamics.soma_segment_ids,
                "spikes": dynamics.spikes,
                "input_events": dynamics.input_events,
                "connectome": dynamics.connectome["metadata"] if dynamics.connectome else None,
                "solver_seconds": dynamics.seconds,
            }
            write_json(pending, {**metadata, "metadata_sha256": metadata_digest(metadata)})
            os.replace(temporary, self.root / (key + ".npz"))
            os.replace(pending, self.root / (key + ".json"))
            self.prune(key)
            return {"status": "miss", "key": key, "engine": self.identity, "data_sha256": digest}
        finally:
            temporary.unlink(missing_ok=True)
            pending.unlink(missing_ok=True)

    def prune(self, keep: str) -> None:
        entries = [
            path
            for path in self.root.glob("*.npz")
            if re.fullmatch(r"[a-f0-9]{64}\.npz", path.name)
        ]
        total = sum(path.stat().st_size for path in entries)
        for path in sorted(entries, key=lambda item: item.stat().st_mtime):
            if total <= self.max_bytes:
                break
            if path.stem == keep:
                continue
            total -= path.stat().st_size
            # Flat, generated filenames in the cache root only; no recursive cleanup.
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)

    def simulate(self, config: SimulationConfig) -> Dynamics:
        key, status = self.key(config), "miss"
        if self.max_bytes <= 0:
            dynamics = self.engine.simulate(config)
            dynamics.cache_info = {"status": "disabled", "key": key, "engine": self.identity}
            return dynamics
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            cached = self.load(config, key)
            if cached is not None:
                return cached
        except (OSError, ValueError, KeyError, TypeError):
            status = "miss_invalid_or_unavailable"
        dynamics = self.engine.simulate(config)
        try:
            info = self.store(dynamics, key)
            if status != "miss":
                info["status"] = status
            dynamics.cache_info = info
        except OSError:
            dynamics.cache_info = {"status": "unavailable", "key": key, "engine": self.identity}
        return dynamics
