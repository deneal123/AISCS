"""Column-form source candidates: the same payload without per-contact dictionaries.

The durable source payload already stores registered contacts as one structured
numpy array. Decoding it into a Python dictionary per contact is what makes the
whole-population feedback pass cost 0.68 ms per cell: the population holds 124
million registered contacts, i.e. ~33 million dictionaries per pass, and every
consumer then reads those dictionaries field by field.

This module keeps the payload as columns and answers the two questions the
feedback pass actually asks of it:

* how many contacts are registered, and how many lie beyond the tolerance
  (CandidateColumns.counts);
* which output compartments to record, and which verified synapses those
  compartments belong to (CandidateColumns.plan).

Both answers are computed with vectorised numpy over the columns and are
compared field by field against the dictionary path by the tests.

Identity is unchanged: the header carries the same keys the dictionary form
carried, and a reader may materialise the dictionaries with
CandidateColumns.rows when a slower consumer still expects them.
"""

import json
import struct

import numpy as np

# The durable payload layout lives here so that the reader below and the writer
# in :mod:`source_store` share one definition without importing each other: the
# store imports this module, never the other way round.
FORMAT = 'malecns-source-candidates-v2'
_CANDIDATE = np.dtype([('partner', '<i8'), ('position', '<i4', (3,)),
                       ('child', '<i4'), ('fraction', '<f8'), ('distance', '<f8'),
                       ('index', '<i4'), ('included', '<u1')])


class CandidateColumns:
    """One cell's verified source contacts, kept as columns.

    The object is opaque to the feedback planner: only the two methods below
    describe it, and nothing may mutate the payload in place.
    """

    __slots__ = ('header', 'array')

    def __init__(self, header, array):
        if (not isinstance(header, dict) or not isinstance(array, np.ndarray)
                or array.dtype != _CANDIDATE or array.ndim != 1):
            raise ValueError('Invalid source candidate columns')
        self.header = header
        self.array = array

    def __len__(self):
        return int(self.array.size)

    def __eq__(self, other):
        # Diagnostics are compared for equality by callers that read the same
        # batch twice (once mapped, once restored from the batch): the column
        # form has to answer that comparison without materialising rows.
        if not isinstance(other, CandidateColumns):
            return NotImplemented
        return (self.header == other.header
                and self.array.dtype == other.array.dtype
                and np.array_equal(self.array, other.array))

    def counts(self, max_distance_um):
        """Return (registered, unresolved) contacts without building rows."""
        registered = self.array['included'] == 1
        return (int(np.count_nonzero(registered)),
                int(np.count_nonzero(registered
                                     & (self.array['distance'] > max_distance_um))))

    def rows(self):
        """Materialise the dictionary form for consumers that still need it."""
        array = self.array
        partners = array['partner'].tolist()
        positions = array['position'].tolist()
        children = array['child'].tolist()
        fractions = array['fraction'].tolist()
        distances = array['distance'].tolist()
        indices = array['index'].tolist()
        included = array['included'].tolist()
        limit = self.header.get('max_distance_um')
        unresolved = 'geometry_unresolved'
        resolved = 'timing_or_trace_ambiguous'
        return [
            {'included_in_graph': flag == 1, 'partner_id': str(partner),
             'source_position_8nm': position, 'child_node_id': child,
             'segment_fraction': fraction, 'centerline_distance_um': distance,
             'result_segment_index': index,
             'status': unresolved if distance > limit else resolved,
             'stimulated_ticks_ms': None, 'control_ticks_ms': None}
            for partner, position, child, fraction, distance, index, flag in
            zip(partners, positions, children, fractions, distances, indices, included)]

    def plan(self, body, ids, provenance, *, threshold_mv, duration_ms,
             include_candidates, include_unresolved_candidates, max_source_distance_um):
        """Return the deferred output plan the dictionary walk would return."""
        from service.application.feedback.output_columns import column_output_plan

        return column_output_plan(body, ids, provenance, self, threshold_mv=threshold_mv,
            duration_ms=duration_ms, include_candidates=include_candidates,
            include_unresolved_candidates=include_unresolved_candidates,
            max_source_distance_um=max_source_distance_um)


def columns_from_mapping(mapping, max_distance_um):
    """Wrap a freshly mapped cell (dictionary form) as columns."""
    if not isinstance(mapping, dict) or not isinstance(mapping.get('candidates'), list):
        raise ValueError('Invalid source candidate mapping')
    rows = mapping['candidates']
    array = np.zeros(len(rows), dtype=_CANDIDATE)
    if rows:
        array['partner'] = np.fromiter((int(row['partner_id']) for row in rows),
                                       dtype='<i8', count=len(rows))
        array['position'] = np.fromiter(
            (value for row in rows for value in row['source_position_8nm']),
            dtype='<i4', count=3 * len(rows)).reshape(len(rows), 3)
        array['child'] = np.fromiter((int(row['child_node_id']) for row in rows),
                                     dtype='<i4', count=len(rows))
        array['fraction'] = np.fromiter((float(row['segment_fraction']) for row in rows),
                                        dtype='<f8', count=len(rows))
        array['distance'] = np.fromiter((float(row['centerline_distance_um']) for row in rows),
                                        dtype='<f8', count=len(rows))
        array['index'] = np.fromiter((int(row['result_segment_index']) for row in rows),
                                     dtype='<i4', count=len(rows))
        array['included'] = np.fromiter(
            (1 if row['included_in_graph'] is True else 0 for row in rows),
            dtype='<u1', count=len(rows))
    # The in-memory header stays canonical: 'format' and 'rows' belong to the
    # durable payload (columns_from_payload pops them), so a header must not
    # carry them or a mapped batch and a restored batch would not compare equal.
    header = {key: value for key, value in mapping.items()
              if key not in ('candidates', 'format', 'rows')}
    header['max_distance_um'] = max_distance_um
    return CandidateColumns(header, array)


def columns_from_payload(payload, max_distance_um):
    """Parse one verified durable payload into columns."""
    if len(payload) < 4:
        raise ValueError('Truncated source diagnostics payload')
    (size,) = struct.unpack('<I', payload[:4])
    head = json.loads(payload[4:4 + size])
    if head.pop('format', None) != FORMAT or 'rows' not in head:
        raise ValueError('Unknown source diagnostics payload format')
    body = payload[4 + size:]
    rows = int(head.pop('rows'))
    if len(body) != rows * _CANDIDATE.itemsize:
        raise ValueError('Truncated source diagnostics payload')
    head['max_distance_um'] = max_distance_um
    return CandidateColumns(head, np.frombuffer(body, dtype=_CANDIDATE))
