"""Read bounded, hash-verified source event summaries for a target neuron."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter

from service.infrastructure.storage.bounded_download import settled_thread


def _has_crossing_intervals(metadata, body, target_id, schedule):
    """Indicate coverage only; the executor independently verifies each interval."""
    diagnostics = metadata.get('diagnostics')
    if not isinstance(diagnostics, list):
        return False
    matching = [item for item in diagnostics
                if isinstance(item, dict) and item.get('body_id') == str(body)]
    if len(matching) != 1 or not isinstance(matching[0].get('candidates'), list):
        return False
    counts = Counter()
    for row in matching[0]['candidates']:
        if (not isinstance(row, dict) or row.get('included_in_graph') is not True
                or row.get('partner_id') != str(target_id)):
            continue
        ticks, intervals = row.get('stimulated_ticks_ms'), row.get('stimulated_crossing_intervals')
        if ticks == [] and intervals is None:
            continue
        if (not isinstance(ticks, list) or not isinstance(intervals, list)
                or len(ticks) != len(intervals)):
            return False
        for tick, interval in zip(ticks, intervals, strict=True):
            if (type(tick) is not int or not isinstance(interval, dict)
                    or interval.get('tick_ms') != tick
                    or type(interval.get('lower_ms')) not in (int, float)
                    or type(interval.get('upper_ms')) not in (int, float)):
                return False
            counts[tick] += 1
    expected = Counter()
    for event in schedule['edge_events']:
        if event.get('target_id') == target_id:
            expected[event['tick']] += event['count']
    return bool(expected) and counts == expected


async def fragment_target_candidates(storage, source, target_id):
    if type(target_id) is not int or not 0 < target_id < 2**63:
        raise ValueError('invalid_target')
    source_ids = source.configuration.get('source_ids')
    simulation = source.configuration.get('simulation')
    if (not isinstance(source_ids, list) or not source_ids or target_id in source_ids
            or not isinstance(simulation, dict)
            or type(simulation.get('duration_ms')) not in (int, float)):
        raise ValueError('invalid_source_configuration')
    model = next((item for item in source.files if item.name == 'model.json'), None)
    if model is None or model.size > 256 * 1024 * 1024:
        raise ValueError('source_model_unavailable')
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b') as stream:
        size = await storage.download_file_stream(file_key=model.storage_key, target=stream,
                                                  max_bytes=model.size)
        if size != model.size or stream.tell() != model.size:
            raise ValueError('source_model_size_mismatch')
        def read_checked():
            stream.seek(0)
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            if digest.hexdigest() != model.sha256:
                raise ValueError('source_model_checksum_mismatch')
            stream.seek(0)
            def invalid_constant(value):
                raise ValueError(f'invalid_number:{value}')
            return json.load(stream, parse_constant=invalid_constant)
        metadata = await settled_thread(read_checked)
    schedules = metadata.get('schedules') if isinstance(metadata, dict) else None
    if (not isinstance(metadata, dict) or metadata.get('configuration') != source.configuration
            or metadata.get('configuration_sha256') != source.manifest['configuration_sha256']
            or not isinstance(schedules, list) or len(schedules) != len(source_ids)):
        raise ValueError('source_model_mismatch')
    candidates = []
    for body, schedule in zip(source_ids, schedules, strict=True):
        if (type(body) is not int or not isinstance(schedule, dict)
                or schedule.get('source_id') != body
                or schedule.get('graph_sha256') != source.manifest['graph_sha256']
                or not isinstance(schedule.get('edge_events'), list)):
            raise ValueError('source_schedule_mismatch')
        total, first = 0, None
        for event in schedule['edge_events']:
            if not isinstance(event, dict):
                raise ValueError('invalid_source_event')
            if event.get('target_id') != target_id:
                continue
            if (event.get('source_id') != body or type(event.get('tick')) is not int
                    or not 1 <= event['tick'] <= simulation['duration_ms']
                    or type(event.get('count')) is not int or event['count'] <= 0):
                raise ValueError('invalid_target_event')
            total += event['count']
            first = event['tick'] if first is None else min(first, event['tick'])
        if total:
            candidates.append({
                'source_id': body, 'events': total, 'first_tick_ms': first,
                'intervals_available': _has_crossing_intervals(metadata, body, target_id, schedule),
            })
    return {'target_id': target_id, 'candidates': candidates,
            'interpretation': 'modelled graph events; target geometry and physiology unverified'}
