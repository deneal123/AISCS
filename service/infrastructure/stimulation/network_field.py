"""Streaming field summaries on registered SWCs, without inferring excitation."""

from __future__ import annotations

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from itertools import islice

import numpy as np

from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.morphology_field import (
    _evaluate_validated_swc_field,
    _geometry_from_validated_nodes,
    evaluate_registered_neuron_field,
)
from service.infrastructure.stimulation.point_field import bipolar_potential_mv


def _summary(result):
    curvature = result['curvature_mv_per_um2']
    if len(curvature):
        index = int(np.argmax(np.abs(curvature)))
        extremum = float(curvature[index])
        vertex_id = int(result['curvature_vertex_ids'][index])
    else:
        extremum, vertex_id = None, None
    return {
        'body_id': result['body_id'],
        'status': 'partial_geometry' if result['omitted_zero_length_edges'] else 'ok',
        'source_sha256': result['source_sha256'],
        'vertices': len(result['vertex_ids']), 'curvature_vertices': len(curvature),
        'max_abs_curvature_signed_mv_per_um2': extremum, 'extremum_vertex_id': vertex_id,
        'coordinate_frame': result['coordinate_frame'], 'interpretation': 'field-only',
        'omitted_zero_length_edges': result['omitted_zero_length_edges'],
        'omitted_curvature_vertices': result['omitted_curvature_vertices'],
    }


def _gpu_batch(entries, source_um, return_um, current_na, conductivity_s_m, clearance_um,
               allow_degenerate):
    """Evaluate one bounded group, isolating invalid geometries without dropping peers."""
    from service.infrastructure.stimulation.point_field_gpu import bipolar_potential_groups_gpu

    if not entries:
        return []
    try:
        values = bipolar_potential_groups_gpu(
            [entry['points'] for entry in entries], source_um, return_um, current_na,
            conductivity_s_m, clearance_um=clearance_um, isolate_invalid=True,
        )
    except ValueError as exc:
        if len(entries) == 1:
            return [{'body_id': entries[0]['skeleton']['body_id'],
                     'status': 'invalid_geometry_or_field', 'reason': str(exc)}]
        middle = len(entries) // 2
        args = (source_um, return_um, current_na, conductivity_s_m, clearance_um, allow_degenerate)
        return _gpu_batch(entries[:middle], *args) + _gpu_batch(entries[middle:], *args)
    output = []
    for entry, potential in zip(entries, values, strict=True):
        skeleton = entry['skeleton']
        if isinstance(potential, ValueError):
            output.append({'body_id': skeleton['body_id'],
                           'status': 'invalid_geometry_or_field', 'reason': str(potential)})
            continue
        try:
            data = _evaluate_validated_swc_field(
                '', source_um, return_um, current_na, conductivity_s_m,
                clearance_um=clearance_um, allow_degenerate=allow_degenerate,
                field_backend='gpu', potential_override=potential,
                geometry_override=entry['geometry'],
            )
            output.append(_summary({**data, 'body_id': skeleton['body_id'],
                                    'source_sha256': skeleton['sha256'],
                                    'coordinate_frame': 'male-cns-v1.0-native-um'}))
        except (ValueError, OSError) as exc:
            output.append({'body_id': skeleton['body_id'], 'status': 'invalid_geometry_or_field',
                           'reason': str(exc)})
    return output


def _prepare_gpu_skeleton(arguments):
    raw_id, directories = arguments
    body_id = int(raw_id)
    try:
        skeleton = read_skeleton(body_id, directories, topology_only=True,
                                 include_validated_nodes=True)
        geometry = _geometry_from_validated_nodes(skeleton.pop('validated_nodes'))
        # All geometry has already been validated; avoid sending SWC text
        # through the worker pipe as a second copy of the same information.
        skeleton.pop('swc')
        points = geometry[1]
        if len(points) > 1_000_000:
            raise ValueError('Neuron exceeds GPU batch point limit')
        return {'skeleton': skeleton, 'points': points, 'geometry': geometry}
    except FileNotFoundError:
        return {'body_id': str(body_id), 'status': 'source_missing'}
    except (ValueError, OSError) as exc:
        return {'body_id': str(body_id), 'status': 'invalid_geometry_or_field',
                'reason': str(exc)}


def _gpu_prepared_skeletons(ids, directories, workers):
    if workers == 1:
        for raw_id in ids:
            yield _prepare_gpu_skeleton((raw_id, directories))
        return
    # Workers prepare bounded chunks only; CUDA remains in the owning process.
    iterator = iter(ids)
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn')) as pool:
        while batch := list(islice(iterator, 64)):
            yield from pool.map(_prepare_gpu_skeleton,
                                ((raw_id, directories) for raw_id in batch), chunksize=4)


def _gpu_summaries(ids, directories, source_um, return_um, current_na, conductivity_s_m,
                   clearance_um, allow_degenerate, workers):
    args = (source_um, return_um, current_na, conductivity_s_m, clearance_um, allow_degenerate)
    pending, size = [], 0
    for entry in _gpu_prepared_skeletons(ids, directories, workers):
        if 'status' in entry:
            yield from _gpu_batch(pending, *args)
            pending, size = [], 0
            yield entry
            continue
        points = entry['points']
        if pending and (len(pending) >= 64 or size + len(points) > 1_000_000):
            yield from _gpu_batch(pending, *args)
            pending, size = [], 0
        pending.append(entry)
        size += len(points)
    yield from _gpu_batch(pending, *args)


def cached_field_summaries(chunks, source_um, return_um, current_na, conductivity_s_m, *,
                           clearance_um, allow_degenerate=False, skip=0):
    """Evaluate verified cached chunks with the established GPU field operator.

    The caller must authenticate the full snapshot and its ordering before
    yielding chunks. A resumed run still reads and verifies its skipped chunks.
    """
    if type(skip) is not int or skip < 0:
        raise ValueError('Invalid cached field resume offset')
    args = (source_um, return_um, current_na, conductivity_s_m, clearance_um, allow_degenerate)
    for entries in chunks:
        if skip:
            count = min(skip, len(entries))
            entries, skip = entries[count:], skip - count
        if entries:
            yield from _gpu_batch(entries, *args)
    if skip:
        raise ValueError('Cached field resume offset exceeds snapshot')


def registered_field_summaries(
    graph, directories, source_um, return_um, current_na, conductivity_s_m, *, clearance_um,
    allow_degenerate=False, field_backend="cpu", field_workers=1,
):
    """Yield one field-only record per registered neuron, including failures.

    Coordinates and curvature use the native EM frame. Summary extrema are
    numerical descriptors, not thresholds, spikes, currents, or biological
    predictions. The generator retains no prior SWC or accumulated result.
    """
    bipolar_potential_mv(
        np.empty((0, 3)), source_um, return_um, current_na, conductivity_s_m,
        clearance_um=clearance_um,
    )
    if not isinstance(field_backend, str) or field_backend not in {"cpu", "gpu"}:
        raise ValueError("Unknown field backend")
    if type(field_workers) is not int or not 1 <= field_workers <= 8:
        raise ValueError("Invalid field worker count")
    if field_backend == 'cpu' and field_workers != 1:
        raise ValueError("CPU workers are managed by the field executor")
    if field_backend == 'gpu':
        yield from _gpu_summaries(graph.ids, directories, source_um, return_um, current_na,
                                  conductivity_s_m, clearance_um, allow_degenerate, field_workers)
        return
    for raw_id in graph.ids:
        body_id = int(raw_id)
        try:
            result = evaluate_registered_neuron_field(
                body_id, directories, source_um, return_um, current_na, conductivity_s_m,
                clearance_um=clearance_um, allow_degenerate=allow_degenerate,
                field_backend=field_backend,
            )
        except FileNotFoundError:
            yield {"body_id": str(body_id), "status": "source_missing"}
            continue
        except (ValueError, OSError) as exc:
            yield {"body_id": str(body_id), "status": "invalid_geometry_or_field",
                   "reason": str(exc)}
            continue
        yield _summary(result)
