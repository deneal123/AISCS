"""Resumable field-only summaries for registered neural morphology."""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor
from itertools import islice
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from service.infrastructure.connectome import morphology, morphology_repository
from service.infrastructure.stimulation import (
    isolated_roots,
    morphology_field,
    network_field,
    point_field,
)
from service.infrastructure.stimulation.network_field import registered_field_summaries
from service.infrastructure.stimulation.point_field import bipolar_potential_mv


def _field_batch(arguments):
    ids, directories, config, allow_degenerate, field_backend = arguments
    return list(registered_field_summaries(SimpleNamespace(ids=ids), directories, **config,
                                           allow_degenerate=allow_degenerate,
                                           field_backend=field_backend))


def _field_rows(ids, directories, config, allow_degenerate, workers, field_backend):
    if workers == 1:
        yield from registered_field_summaries(SimpleNamespace(ids=ids), directories, **config,
                                               allow_degenerate=allow_degenerate,
                                               field_backend=field_backend)
        return
    # Limit submitted work and retained results even for the complete connectome.
    iterator = iter(ids)
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn')) as pool:
        while batch := list(islice(iterator, workers * 16)):
            tasks = [(batch[i:i + 16], directories, config, allow_degenerate, field_backend)
                     for i in range(0, len(batch), 16)]
            for rows in pool.map(_field_batch, tasks, chunksize=1):
                yield from rows


def compute(ids, directories, output: Path, config: dict, *, graph_hash: str, progress=None,
            allow_degenerate=False, workers=1, field_backend="cpu", check_row=None):
    """Append verified, ordered records; incomplete or incompatible files fail closed."""
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("workers must be an integer between 1 and 8")
    if check_row is not None and not callable(check_row):
        raise ValueError('check_row must be callable')
    if not isinstance(field_backend, str) or field_backend not in {"cpu", "gpu"}:
        raise ValueError("Unknown field backend")
    if field_backend == "gpu" and workers != 1:
        raise ValueError("GPU field execution requires one process")
    bipolar_potential_mv(np.empty((0, 3)), **config)
    algorithm = hashlib.sha256()
    modules = [morphology, morphology_repository, morphology_field, network_field,
               point_field, isolated_roots]
    device_info = None
    if field_backend == "gpu":
        import numba

        from service.infrastructure.stimulation import point_field_gpu

        cuda, _ = point_field_gpu._kernel()
        device = cuda.get_current_device()
        name = device.name.decode("utf-8") if isinstance(device.name, bytes) else str(device.name)
        device_info = {"numba_version": numba.__version__,
                       "cuda_runtime": list(cuda.runtime.get_version()),
                       "device": name, "compute_capability": list(device.compute_capability)}
        modules.append(point_field_gpu)
    for module in modules:
        algorithm.update(module.__name__.encode() + b"\0" + Path(module.__file__).read_bytes())
    header = {"kind": "header", "format": "malecns-field-summary-v1", "graph_sha256": graph_hash,
              "neurons": len(ids), "configuration": config, "allow_degenerate": allow_degenerate,
              "coordinate_frame": "male-cns-v1.0-native-um",
              "medium": "infinite-homogeneous-isotropic",
              "algorithm_sha256": algorithm.hexdigest(), "numpy_version": np.__version__,
              "field_backend": field_backend, "device_info": device_info,
              "interpretation": "field-only; no excitation or anatomical registration"}
    def advance(previous, row):
        canonical = json.dumps(row, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(bytes.fromhex(previous) + canonical).hexdigest()

    chain = hashlib.sha256(json.dumps(header, sort_keys=True).encode()).hexdigest()
    completed = 0
    if output.exists():
        with output.open(encoding="utf-8") as existing:
            try:
                first = existing.readline()
                if not first.endswith("\n") or json.loads(first) != header:
                    raise ValueError("Field file has different provenance or configuration")
                for line in existing:
                    if not line.endswith("\n"):
                        raise ValueError("Existing field file has an incomplete record")
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("Invalid field record")
                    if row.get("kind") == "footer":
                        if (row.get("neurons") != len(ids) or completed != len(ids)
                                or row.get("chain_sha256") != chain or existing.read(1)):
                            raise ValueError("Invalid completion footer")
                        return completed
                    if (completed >= len(ids) or row.get("body_id") != str(ids[completed])
                            or row.get("status") not in {
                                "ok", "partial_geometry", "source_missing",
                                "invalid_geometry_or_field",
                            }):
                        raise ValueError("Existing field records do not match the graph")
                    if check_row is not None:
                        check_row(row)
                    previous = row.pop("chain_sha256", None)
                    chain = advance(chain, row)
                    if previous != chain:
                        raise ValueError("Existing field record checksum mismatch")
                    completed += 1
            except json.JSONDecodeError as exc:
                raise ValueError("Existing field file is not valid JSONL") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if output.exists() else "x"
    with output.open(mode, encoding="utf-8", newline="\n") as stream:
        if mode == "x":
            stream.write(json.dumps(header, allow_nan=False, sort_keys=True) + "\n")
            stream.flush()
        for row in _field_rows(ids[completed:], directories, config, allow_degenerate, workers,
                               field_backend):
            if check_row is not None:
                check_row(row)
            chain = advance(chain, row)
            row["chain_sha256"] = chain
            stream.write(json.dumps(row, allow_nan=False, sort_keys=True) + "\n")
            completed += 1
            if completed % 1000 == 0:
                stream.flush()
                os.fsync(stream.fileno())
                if progress:
                    progress(completed, len(ids))
        footer = {"kind": "footer", "neurons": completed, "chain_sha256": chain}
        stream.write(json.dumps(footer) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return completed
