"""Streaming field summaries on registered SWCs, without inferring excitation."""

from __future__ import annotations

import numpy as np

from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.morphology_field import (
    _evaluate_validated_swc_field,
    _parse_swc_geometry,
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
            conductivity_s_m, clearance_um=clearance_um,
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
        try:
            data = _evaluate_validated_swc_field(
                skeleton['swc'], source_um, return_um, current_na, conductivity_s_m,
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


def _gpu_summaries(ids, directories, source_um, return_um, current_na, conductivity_s_m,
                   clearance_um, allow_degenerate):
    args = (source_um, return_um, current_na, conductivity_s_m, clearance_um, allow_degenerate)
    pending, size = [], 0
    for raw_id in ids:
        body_id = int(raw_id)
        try:
            skeleton = read_skeleton(body_id, directories)
            geometry = _parse_swc_geometry(skeleton['swc'])
            points = geometry[1]
            if len(points) > 1_000_000:
                raise ValueError('Neuron exceeds GPU batch point limit')
        except FileNotFoundError:
            yield from _gpu_batch(pending, *args)
            pending, size = [], 0
            yield {'body_id': str(body_id), 'status': 'source_missing'}
            continue
        except (ValueError, OSError) as exc:
            yield from _gpu_batch(pending, *args)
            pending, size = [], 0
            yield {'body_id': str(body_id), 'status': 'invalid_geometry_or_field',
                   'reason': str(exc)}
            continue
        if pending and (len(pending) >= 64 or size + len(points) > 1_000_000):
            yield from _gpu_batch(pending, *args)
            pending, size = [], 0
        pending.append({'skeleton': skeleton, 'points': points, 'geometry': geometry})
        size += len(points)
    yield from _gpu_batch(pending, *args)


def registered_field_summaries(
    graph, directories, source_um, return_um, current_na, conductivity_s_m, *, clearance_um,
    allow_degenerate=False, field_backend="cpu",
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
    if field_backend == 'gpu':
        yield from _gpu_summaries(graph.ids, directories, source_um, return_um, current_na,
                                  conductivity_s_m, clearance_um, allow_degenerate)
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
