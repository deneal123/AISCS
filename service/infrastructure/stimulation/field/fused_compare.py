"""Audit experimental GPU summaries against the established field operator.

This is an offline field-only comparison, not a physiological validation or
an assertion that either operator predicts excitation.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from time import perf_counter

import numba

from service.infrastructure.connectome.dataset import digest
from service.infrastructure.stimulation import (
    experimental_fused_gpu,
    network_field,
    point_field_gpu,
)
from service.infrastructure.stimulation.experimental_fused_gpu import experimental_summaries
from service.infrastructure.stimulation.field.summary_audit import audit as audit_field
from service.infrastructure.stimulation.geometry_cache.cache import iter_cache
from service.infrastructure.stimulation.network_field import _gpu_batch


def compare_cache(*, geometry_cache, graph_ids, graph_sha256, configuration,
                  allow_degenerate=False, progress=None, reference_field=None):
    """Compare every cached cell; retain only bounded discrepancy details."""
    if type(allow_degenerate) is not bool or (progress is not None and not callable(progress)):
        raise ValueError('Invalid field comparison options')
    if not isinstance(configuration, dict) or set(configuration) != {
        'source_um', 'return_um', 'current_na', 'conductivity_s_m', 'clearance_um',
    }:
        raise ValueError('Invalid field comparison configuration')
    modules = (experimental_fused_gpu, network_field, point_field_gpu)
    source_hashes = {module.__name__: digest(Path(module.__file__)) for module in modules}
    source_hashes[__name__] = digest(Path(__file__))
    reference_hash = None
    reference_rows = None
    reference_mismatches = 0
    reference_examples = []
    if reference_field is not None:
        reference_field = Path(reference_field)
        reference_hash = digest(reference_field)
        audit_field(reference_field, graph_ids, graph_hash=graph_sha256)
        def records():
            with reference_field.open(encoding='utf8') as stream:
                header = json.loads(next(stream))
                if (header.get('configuration') != configuration
                        or header.get('allow_degenerate') != allow_degenerate):
                    raise ValueError('Reference field configuration does not match')
                for line in stream:
                    row = json.loads(line)
                    if row.get('kind') == 'footer':
                        return
                    row.pop('chain_sha256', None)
                    yield row
        reference_rows = iter(records())
    cuda, _ = point_field_gpu._kernel()
    device = cuda.get_current_device()
    name = device.name.decode('utf8') if isinstance(device.name, bytes) else str(device.name)
    chunks = iter_cache(**geometry_cache, graph_ids=graph_ids, graph_sha256=graph_sha256)
    expected_total, processed, mismatches, fallbacks = len(graph_ids), 0, 0, 0
    load_seconds = baseline_seconds = fused_seconds = 0.
    max_absolute, details = 0., []
    start = perf_counter()
    while True:
        before = perf_counter()
        try:
            entries = next(chunks)
        except StopIteration:
            load_seconds += perf_counter() - before
            break
        load_seconds += perf_counter() - before
        before = perf_counter()
        baseline = _gpu_batch(entries, configuration['source_um'], configuration['return_um'],
                              configuration['current_na'], configuration['conductivity_s_m'],
                              configuration['clearance_um'], allow_degenerate)
        baseline_seconds += perf_counter() - before
        before = perf_counter()
        fused, count = experimental_summaries(entries, **configuration,
                                              allow_degenerate=allow_degenerate)
        fused_seconds += perf_counter() - before
        fallbacks += count
        if len(baseline) != len(entries) or len(fused) != len(entries):
            raise ValueError('Field comparison returned incomplete batch')
        for expected, actual in zip(baseline, fused, strict=True):
            expected, actual = expected.copy(), actual.copy()
            if reference_rows is not None:
                try:
                    reference = next(reference_rows)
                except StopIteration as exc:
                    raise ValueError('Reference field ended early') from exc
                reference_value = reference.pop('max_abs_curvature_signed_mv_per_um2', None)
                baseline_value = expected.get('max_abs_curvature_signed_mv_per_um2')
                baseline_metadata = expected.copy()
                baseline_metadata.pop('max_abs_curvature_signed_mv_per_um2', None)
                same = reference == baseline_metadata and ((reference_value is None)
                                                           == (baseline_value is None))
                if reference_value is not None and baseline_value is not None:
                    same &= math.isclose(reference_value, baseline_value,
                                         rel_tol=1e-9, abs_tol=1e-12)
                if not same:
                    reference_mismatches += 1
                    if len(reference_examples) < 25:
                        reference_examples.append({
                            'body_id': reference.get('body_id'),
                            'expected_status': reference.get('status'),
                            'actual_status': baseline_metadata.get('status'),
                            'expected_vertex': reference.get('extremum_vertex_id'),
                            'actual_vertex': baseline_metadata.get('extremum_vertex_id'),
                            'expected': reference_value, 'actual': baseline_value,
                        })
            a = expected.pop('max_abs_curvature_signed_mv_per_um2', None)
            b = actual.pop('max_abs_curvature_signed_mv_per_um2', None)
            different = expected != actual or ((a is None) != (b is None))
            if a is not None and b is not None:
                if not math.isfinite(a) or not math.isfinite(b):
                    different = True
                else:
                    max_absolute = max(max_absolute, abs(a - b))
                    different |= not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
            if different:
                mismatches += 1
                if len(details) < 25:
                    details.append({'body_id': expected.get('body_id'),
                                    'expected_status': expected.get('status'),
                                    'actual_status': actual.get('status'),
                                    'expected_vertex': expected.get('extremum_vertex_id'),
                                    'actual_vertex': actual.get('extremum_vertex_id'),
                                    'expected': a, 'actual': b})
            processed += 1
        if progress is not None:
            progress(processed, expected_total)
    if processed != expected_total:
        raise ValueError('Field comparison did not cover the graph')
    if reference_rows is not None:
        if next(reference_rows, None) is not None:
            raise ValueError('Reference field has extra rows')
        if digest(reference_field) != reference_hash:
            raise ValueError('Reference field changed during comparison')
    current_hashes = {module.__name__: digest(Path(module.__file__)) for module in modules}
    current_hashes[__name__] = digest(Path(__file__))
    if source_hashes != current_hashes:
        raise ValueError('Field operator changed during comparison')
    return {'format': 'malecns-fused-field-comparison-v1', 'graph_sha256': graph_sha256,
            'cache_manifest_sha256': geometry_cache['expected_manifest_sha256'],
            'configuration': configuration, 'allow_degenerate': allow_degenerate,
            'neurons': processed, 'mismatches': mismatches, 'fallbacks': fallbacks,
            'reference_field_sha256': reference_hash,
            'reference_mismatches': reference_mismatches if reference_rows is not None else None,
            'reference_examples': reference_examples,
            'max_absolute_difference': max_absolute, 'examples': details,
            'source_sha256': source_hashes,
            'device': {'name': name, 'numba': numba.__version__,
                       'cuda_runtime': list(cuda.runtime.get_version()),
                       'compute_capability': list(device.compute_capability)},
            'tolerance': {'relative': 1e-9, 'absolute_mv_per_um2': 1e-12},
            'timing_seconds': {'cache_loading': load_seconds, 'baseline': baseline_seconds,
                               'fused': fused_seconds, 'total': perf_counter() - start},
            'scope': 'field summary comparison only; not biological or clinical validation'}
