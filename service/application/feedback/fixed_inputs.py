"""Checked adapter from a candidate feedback schedule to bounded GPU batches."""

import copy
import hashlib
import json
import re


def fixed_input_digest(schedule):
    """Hash the entire JSON-compatible schedule, including all event values."""
    try:
        encoded = json.dumps(schedule, sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode('utf8')
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid fixed input schedule') from exc
    return hashlib.sha256(encoded).hexdigest()


def fixed_input_factory(schedule, expected_ids, morphology_sha256, *, graph_sha256,
                        expected_schedule_sha256):
    """Freeze a complete, identity-matched schedule for one experimental replay.

    The expected schedule hash must be obtained independently from a trusted
    producer. This does not establish biology or convergence. Per-event kinetics
    and segment IDs are checked by the solver.
    """
    if (not isinstance(expected_ids, list) or not expected_ids
            or any(type(body) is not int or body <= 0 for body in expected_ids)
            or len(set(expected_ids)) != len(expected_ids)
            or not isinstance(graph_sha256, str) or not re.fullmatch('[a-f0-9]{64}', graph_sha256)
            or not isinstance(morphology_sha256, dict)
            or set(morphology_sha256) != set(expected_ids)
            or any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)
                   for value in morphology_sha256.values())
            or not isinstance(schedule, dict) or schedule.get('graph_sha256') != graph_sha256
            or schedule.get('source_ids') != expected_ids or schedule.get('unresolved') != []
            or not isinstance(expected_schedule_sha256, str)
            or not re.fullmatch('[a-f0-9]{64}', expected_schedule_sha256)):
        raise ValueError('Incompatible fixed input identity')
    schedule = copy.deepcopy(schedule)
    if fixed_input_digest(schedule) != expected_schedule_sha256:
        raise ValueError('Fixed input schedule digest mismatch')
    events = schedule.get('events_by_target')
    provenance = schedule.get('provenance_by_target')
    target_hashes = schedule.get('target_morphology_sha256')
    ids = set(expected_ids)
    if (not isinstance(events, dict) or set(events) != ids
            or not isinstance(provenance, dict) or set(provenance) != ids
            or not isinstance(target_hashes, dict) or not set(target_hashes).issubset(ids)
            or any(not isinstance(events[body], list) or not isinstance(provenance[body], list)
                   or len(events[body]) != len(provenance[body]) for body in ids)
            or any(events[body] and target_hashes.get(body) != morphology_sha256[body]
                   for body in ids)
            or any(morphology_sha256[body] != digest for body, digest in target_hashes.items())
            or type(schedule.get('event_count')) is not int
            or schedule['event_count'] != sum(map(len, events.values()))):
        raise ValueError('Incomplete fixed input mapping')
    digest = hashlib.sha256(json.dumps(
        {str(body): rows for body, rows in provenance.items()}, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if digest != schedule.get('provenance_sha256'):
        raise ValueError('Fixed input provenance mismatch')
    # ``events`` already belongs to the private deep copy of the schedule.
    # Each returned batch is copied below, so copying the complete population a
    # second time only increases startup cost and peak memory.
    frozen = events

    def get(batch_ids):
        if (not isinstance(batch_ids, tuple) or not batch_ids
                or any(type(body) is not int or body not in ids for body in batch_ids)
                or len(set(batch_ids)) != len(batch_ids)):
            raise ValueError('Invalid fixed input batch')
        return {body: copy.deepcopy(frozen[body]) for body in batch_ids}

    return get


def merge_fixed_input_schedules(schedules, expected_ids, morphology_sha256, *, graph_sha256,
                                max_events):
    """Merge authenticated full schedules without changing individual events."""
    if (not isinstance(schedules, list) or not schedules or type(max_events) is not int
            or max_events < 1 or not isinstance(expected_ids, list) or not expected_ids
            or any(type(body) is not int or body <= 0 for body in expected_ids)
            or len(set(expected_ids)) != len(expected_ids)):
        raise ValueError('Invalid fixed input schedule merge')
    combined_events = {body: [] for body in expected_ids}
    combined_provenance = {body: [] for body in expected_ids}
    hashes, total, outside = {}, 0, 0
    for item in schedules:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ValueError('Invalid fixed input schedule merge')
        schedule, digest = item
        fixed_input_factory(schedule, expected_ids, morphology_sha256, graph_sha256=graph_sha256,
                            expected_schedule_sha256=digest)
        if type(schedule.get('outside_window')) is not int or schedule['outside_window'] < 0:
            raise ValueError('Invalid fixed input window count')
        total += schedule['event_count']
        outside += schedule['outside_window']
        if total > max_events:
            raise ValueError('Combined fixed input exceeds event limit')
        for body in expected_ids:
            combined_events[body].extend(copy.deepcopy(schedule['events_by_target'][body]))
            combined_provenance[body].extend(copy.deepcopy(schedule['provenance_by_target'][body]))
        for body, digest in schedule['target_morphology_sha256'].items():
            if body in hashes and hashes[body] != digest:
                raise ValueError('Inconsistent fixed input target morphology')
            hashes[body] = digest
    proof_digest = hashlib.sha256(json.dumps(
        {str(body): rows for body, rows in combined_provenance.items()}, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {'graph_sha256': graph_sha256, 'source_ids': expected_ids.copy(),
        'target_morphology_sha256': hashes, 'events_by_target': combined_events,
        'provenance_by_target': combined_provenance, 'provenance_sha256': proof_digest,
        'event_count': total, 'outside_window': outside, 'unresolved': [],
        'interpretation': 'merged fixed inputs; no network convergence or validation'}
