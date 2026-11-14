"""Explicit, opt-in contraction of one verified zero-length SWC edge.

The result is a derived geometry, never a replacement for the original.
Synapse mapping and electrical equivalence require independent verification.
"""

import hashlib
import math


def contract_zero_edge(raw, *, expected_sha256, parent_id, child_id):
    if (not isinstance(raw, bytes) or not isinstance(expected_sha256, str)
            or hashlib.sha256(raw).hexdigest() != expected_sha256
            or type(parent_id) is not int or type(child_id) is not int
            or parent_id <= 0 or child_id <= 0 or parent_id == child_id):
        raise ValueError('Invalid zero-edge transform identity')
    try:
        lines = raw.decode('utf-8').splitlines()
        nodes = {}
        for line in lines:
            text = line.strip()
            if not text or text.startswith('#'):
                continue
            fields = text.split()
            if len(fields) != 7:
                raise ValueError('Invalid SWC row')
            body, parent = int(fields[0]), int(fields[6])
            values = tuple(float(value) for value in fields[2:6])
            if (body <= 0 or body in nodes or any(not math.isfinite(x) for x in values)
                    or values[3] <= 0):
                raise ValueError('Invalid SWC node')
            nodes[body] = (parent, values)
    except (UnicodeError, OverflowError) as exc:
        raise ValueError('Invalid SWC encoding or node') from exc
    if (parent_id not in nodes or child_id not in nodes or nodes[child_id][0] != parent_id
            or nodes[parent_id][1][:3] != nodes[child_id][1][:3]):
        raise ValueError('Specified edge is not a zero-length parent-child edge')
    if any(parent != -1 and parent not in nodes for parent, _ in nodes.values()):
        raise ValueError('SWC parent is missing')
    checked = set()
    for node in nodes:
        trail = set()
        current = node
        while current != -1 and current not in checked:
            if current in trail:
                raise ValueError('SWC contains a cycle')
            trail.add(current)
            current = nodes[current][0]
        checked.update(trail)
    if any(node != child_id and parent != -1 and values[:3] == nodes[parent][1][:3]
           for node, (parent, values) in nodes.items()):
        raise ValueError('SWC contains other zero-length edges')
    result, reassigned = [], []
    for line in lines:
        text = line.strip()
        if not text or text.startswith('#'):
            result.append(line)
            continue
        fields = text.split()
        node = int(fields[0])
        if node == child_id:
            continue
        if int(fields[6]) == child_id:
            fields[6] = str(parent_id)
            line = ' '.join(fields)
            reassigned.append(node)
        result.append(line)
    derived = ('\n'.join(result) + '\n').encode('utf-8')
    return derived, {'source_sha256': expected_sha256,
                     'derived_sha256': hashlib.sha256(derived).hexdigest(),
                     'contracted_parent_id': parent_id, 'contracted_child_id': child_id,
                     'reassigned_child_ids': reassigned,
                     'interpretation': 'derived geometry; electrical equivalence unverified'}
