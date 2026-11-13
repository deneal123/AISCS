"""Resumable field-only summaries for registered neural morphology."""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor
from itertools import chain as itertools_chain
from itertools import islice
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from service.infrastructure.connectome import morphology, morphology_repository
from service.infrastructure.execution import pool_lifecycle
from service.infrastructure.execution.pool_lifecycle import guard_pool_owner
from service.infrastructure.stimulation import (
    isolated_roots,
    morphology_field,
    network_field,
    point_field,
)
from service.infrastructure.stimulation.network_field import registered_field_summaries
from service.infrastructure.stimulation.point_field import bipolar_potential_mv

_ROW_STATUSES = frozenset({
    "ok", "partial_geometry", "source_missing", "invalid_geometry_or_field",
})


def _check_ordered_row(row, ids, completed):
    """Reject missing, unexpected or out-of-order results before publishing them."""
    if (not isinstance(row, dict) or completed >= len(ids)
            or row.get("body_id") != str(ids[completed])
            or not isinstance(row.get("status"), str)
            or row["status"] not in _ROW_STATUSES):
        raise ValueError("Field records do not match the graph")


def _field_batch(arguments):
    ids, directories, config, allow_degenerate, field_backend = arguments
    return list(registered_field_summaries(SimpleNamespace(ids=ids), directories, **config,
                                           allow_degenerate=allow_degenerate,
                                           field_backend=field_backend))


def _field_rows(ids, directories, config, allow_degenerate, workers, field_backend):
    if field_backend == 'gpu':
        yield from registered_field_summaries(SimpleNamespace(ids=ids), directories, **config,
                                               allow_degenerate=allow_degenerate,
                                               field_backend=field_backend, field_workers=workers)
        return
    if workers == 1:
        yield from registered_field_summaries(SimpleNamespace(ids=ids), directories, **config,
                                               allow_degenerate=allow_degenerate,
                                               field_backend=field_backend)
        return
    # Limit submitted work and retained results even for the complete connectome.
    iterator = iter(ids)
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn'),
                             initializer=guard_pool_owner, initargs=(os.getpid(),)) as pool:
        while batch := list(islice(iterator, workers * 16)):
            tasks = [(batch[i:i + 16], directories, config, allow_degenerate, field_backend)
                     for i in range(0, len(batch), 16)]
            for rows in pool.map(_field_batch, tasks, chunksize=1):
                yield from rows


def _fused_field_rows(chunks, config, allow_degenerate, skip):
    """Regroup verified entries for the opt-in experimental fused operator."""
    from service.infrastructure.stimulation.experimental_fused_gpu import experimental_summaries
    from service.infrastructure.stimulation.geometry_batching import batch_geometry

    entries = itertools_chain.from_iterable(chunks)
    remaining = islice(entries, skip, None)
    for group in batch_geometry([remaining], max_neurons=384, max_vertices=1_000_000):
        rows, _fallbacks = experimental_summaries(group, **config,
                                                   allow_degenerate=allow_degenerate)
        yield from rows


def compute(ids, directories, output: Path, config: dict, *, graph_hash: str, progress=None,
            allow_degenerate=False, workers=1, field_backend="cpu", check_row=None,
            geometry_cache=None):
    """Append verified, ordered records; incomplete or incompatible files fail closed."""
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("workers must be an integer between 1 and 8")
    if check_row is not None and not callable(check_row):
        raise ValueError('check_row must be callable')
    if not isinstance(field_backend, str) or field_backend not in {"cpu", "gpu", "gpu-fused"}:
        raise ValueError("Unknown field backend")
    if field_backend == 'gpu-fused' and geometry_cache is None:
        raise ValueError('Experimental fused GPU requires an authenticated geometry cache')
    cached_chunks = None
    if geometry_cache is not None:
        from service.infrastructure.stimulation import geometry_prefetch
        from service.infrastructure.stimulation.geometry_cache import cache, chunk, index

        if (field_backend not in ('gpu', 'gpu-fused') or not isinstance(geometry_cache, dict)
                or set(geometry_cache) != {'directory', 'expected_manifest_sha256',
                                           'source_index', 'source_audit'}
                or any(not isinstance(geometry_cache[key], Path)
                       for key in ('directory', 'source_index', 'source_audit'))):
            raise ValueError('Invalid GPU geometry cache configuration')
        cached_chunks = cache.iter_cache(**geometry_cache, graph_ids=ids, graph_sha256=graph_hash)
        try:
            first_chunk = next(cached_chunks)
        except StopIteration as exc:
            raise ValueError('Geometry cache is empty') from exc
        cached_chunks = geometry_prefetch.prefetch(itertools_chain([first_chunk], cached_chunks))
    bipolar_potential_mv(np.empty((0, 3)), **config)
    algorithm = hashlib.sha256()
    modules = [morphology, morphology_repository, morphology_field, network_field,
               point_field, isolated_roots, pool_lifecycle]
    if geometry_cache is not None:
        modules.extend([cache, chunk, index, geometry_prefetch])
    if field_backend == 'gpu-fused':
        from service.infrastructure.stimulation import experimental_fused_gpu, geometry_batching

        modules.extend([experimental_fused_gpu, geometry_batching])
    device_info = None
    if field_backend in ("gpu", "gpu-fused"):
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
    if geometry_cache is not None:
        header['geometry_cache_manifest_sha256'] = geometry_cache['expected_manifest_sha256']
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
                    _check_ordered_row(row, ids, completed)
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
        if cached_chunks is None:
            rows = _field_rows(ids[completed:], directories, config, allow_degenerate, workers,
                               field_backend)
        elif field_backend == 'gpu-fused':
            rows = _fused_field_rows(cached_chunks, config, allow_degenerate, completed)
        else:
            rows = network_field.cached_field_summaries(cached_chunks, **config,
                allow_degenerate=allow_degenerate, skip=completed)
        try:
            for row in rows:
                _check_ordered_row(row, ids, completed)
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
        finally:
            close_rows = getattr(rows, 'close', None)
            if callable(close_rows):
                close_rows()
            if cached_chunks is not None:
                cached_chunks.close()
        if completed != len(ids):
            raise ValueError("Field calculation ended before all graph records were produced")
        footer = {"kind": "footer", "neurons": completed, "chain_sha256": chain}
        stream.write(json.dumps(footer) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        if progress and completed % 1000:
            progress(completed, len(ids))
    return completed
