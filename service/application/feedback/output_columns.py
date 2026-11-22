"""Vectorised output planning over column-form source candidates.

The dictionary planner in :mod:`service.application.feedback.outputs` walks one
Python object per registered contact. The population holds 124 million contacts,
so that walk costs 0.42 ms per cell and allocates ~33 million dictionaries per
pass. The durable payload behind it is a structured numpy array, so the same
answers - which compartments to record, which verified synapses they belong to,
and which contacts are placeholders for unresolvable geometry - follow from
vectorised comparisons over the columns.

Equality with the dictionary planner is not assumed: every validation it
performs is performed here in the same order, and the plan it returns is
compared field by field by the tests. The plan carries its rows lazily, because
the majority of contacts resolve to a compartment that never crossed and their
rows are dropped by the renderer anyway.
"""

import math

import numpy as np

from .outputs import _output_edge_ranges, _verified_output_ids

_UNRESOLVED = 1
_CANDIDATE = 2


class ColumnRows:
    """Ordered, lazily materialised plan rows over the candidate columns.

    The renderer walks these once and keeps only the rows whose compartment
    crossed; the rest are omitted on the spot. Building one tuple per contact
    eagerly is what this path exists to avoid.
    """

    __slots__ = ('_kinds', '_points', '_partners', '_indexes')

    def __init__(self, kinds, points, partners, indexes):
        self._kinds = kinds
        self._points = points
        self._partners = partners
        self._indexes = indexes

    def __len__(self):
        return int(np.count_nonzero(self._kinds))

    def __iter__(self):
        """Yield the rows that survive, converting only those to Python values.

        Converting the whole contact array cost 5.0 ms per cell on the full
        population, because the renderer keeps only the rows of compartments
        that crossed and a silenced cell crosses none: 4 158 irrelevant
        conversions for every cell that reports nothing, which is 168 of
        166 700. Selecting the survivors first makes a quiet cell cost the
        search, not the walk.
        """
        kinds = self._kinds
        orders = np.flatnonzero(kinds)
        if not len(orders):
            return
        chosen = kinds[orders]
        points = self._points[orders].tolist()
        partners = self._partners[orders].tolist()
        indexes = self._indexes[orders].tolist()
        for offset, kind in enumerate(chosen.tolist()):
            partner = str(partners[offset])
            if kind == _UNRESOLVED:
                yield ('unresolved', points[offset], partner, None)
            else:
                yield ('candidate', points[offset], partner, indexes[offset])

    def has_placeholders(self):
        """Return whether any row survives regardless of a crossing.

        An unresolved contact is a placeholder the archive records with an empty
        tick list, so a cell that owns one needs its real plan even when every
        compartment stayed quiet. Cells without one can be answered from the
        selection table alone.
        """
        return bool(np.any(self._kinds == _UNRESOLVED))

    def unresolved(self):
        """Return the placeholder rows without touching the candidate columns."""
        orders = np.flatnonzero(self._kinds == _UNRESOLVED)
        points = self._points[orders].tolist()
        partners = self._partners[orders].tolist()
        return [('unresolved', point, str(partner), None)
                for point, partner in zip(points, partners)]

    def select(self, live):
        """Return the rows kept when only the crossing compartments matter.

        A row exists per contact, not per compartment: a wide cell carries
        11 372 candidate rows behind its 1 499 compartments. The renderer drops
        every row whose compartment reported no crossing, which for a silenced
        cell is all of them - and 168 of 166 700 cells report anything at all.
        Walking 11 372 rows to discard them cost 1.58 s of the 3.27 s a 253-cell
        quiet batch spent rendering. Placeholders survive regardless, because
        the renderer emits them whether or not their compartment crossed.

        The second return value is the archive's omission flag, and it is the
        reason this cannot be a filter with no report: a candidate row withheld
        because its compartment stayed quiet is exactly what the compact archive
        records by leaving it out, so the batch must say that it omitted rows.
        Dropping them silently made every one of those cells claim a complete
        candidate list, and the merge then rejected the archive as incomplete.
        """
        kinds = self._kinds
        candidate = kinds == _CANDIDATE
        live = np.fromiter(sorted(live), dtype=np.int64, count=len(live))
        crossing = (np.isin(self._indexes, live) if len(live)
                    else np.zeros(len(kinds), dtype=bool))
        kept = (kinds == _UNRESOLVED) | (candidate & crossing)
        omitted = bool(np.any(candidate & ~crossing))
        orders = np.flatnonzero(kept)
        points = self._points[orders].tolist()
        partners = self._partners[orders].tolist()
        indexes = self._indexes[orders].tolist()
        rows = ((('unresolved', points[offset], str(partners[offset]), None)
                 if kind == _UNRESOLVED
                 else ('candidate', points[offset], str(partners[offset]), indexes[offset]))
                for offset, kind in enumerate(kinds[orders].tolist()))
        return rows, omitted


def column_output_plan(body, ids, provenance, columns, *, threshold_mv, duration_ms,
                       include_candidates, include_unresolved_candidates,
                       max_source_distance_um):
    """Resolve one cell's verified candidates from columns, without row objects."""
    ids = _verified_output_ids(ids)
    header = columns.header
    array = columns.array
    limit = header.get('max_distance_um')
    if (type(body) is not int or body <= 0 or provenance.get('body_id') != str(body)
            or header.get('body_id') != str(body)
            or provenance.get('morphology_sha256') != header.get('morphology_sha256')
            or header.get('threshold_mv') != threshold_mv
            or header.get('duration_ms') != duration_ms
            or type(include_candidates) is not bool
            or type(include_unresolved_candidates) is not bool
            or (include_unresolved_candidates and not include_candidates)
            or type(limit) not in (int, float) or not math.isfinite(limit)
            or (max_source_distance_um is not None
                and (type(max_source_distance_um) not in (int, float)
                     or not math.isfinite(max_source_distance_um)
                     or max_source_distance_um < 0))):
        raise ValueError('Incompatible output diagnostic identity')
    edge_ranges = _output_edge_ranges(ids, provenance)
    distance = array['distance']
    included = array['included'] == 1
    unresolved = included & (distance > limit)
    if max_source_distance_um is not None:
        if not np.isfinite(distance[included]).all() or (distance[included] < 0).any():
            raise ValueError('Invalid verified source geometry')
        cut = distance <= max_source_distance_um
        if include_unresolved_candidates and np.any(unresolved & cut):
            raise ValueError('Unresolved source candidate requires matching distance cutoff')
        kept = included & cut
        placeholders = unresolved & ~cut if include_unresolved_candidates else np.zeros(
            len(array), dtype=bool)
    else:
        if include_unresolved_candidates and np.any(unresolved):
            raise ValueError('Unresolved source candidate requires matching distance cutoff')
        kept = included
        placeholders = np.zeros(len(array), dtype=bool)
    child = array['child']
    index = _output_index(array, child, kept, edge_ranges)
    partner = array['partner']
    kept_index = index[kept]
    if len(kept_index) and ((kept_index < 0).any() or (kept_index >= len(ids)).any()
                            or np.any(ids[kept_index] != child[kept])
                            or (partner[kept] <= 0).any()):
        raise ValueError('Invalid verified output compartment')
    points = array['position']
    if include_candidates:
        if np.any(points[kept] < 0):
            raise ValueError('Missing source coordinate')
        if _conflicting_duplicates(array['partner'][kept], points[kept], kept_index):
            raise ValueError('Conflicting duplicate source coordinate')
        if placeholders.any() and (np.any(points[placeholders] < 0)
                                   or (partner[placeholders] <= 0).any()):
            raise ValueError('Invalid unresolved source candidate')
    positions = _ordered_unique(kept_index)
    partners = DeferredPartners(kept_index, partner[kept])
    kinds = np.zeros(len(array), dtype=np.int8)
    kinds[kept] = _CANDIDATE
    kinds[placeholders] = _UNRESOLVED
    return {'body': body, 'ids': ids, 'pipelines': edge_ranges,
            'duration_ms': duration_ms, 'indices': positions,
            'ticks': {value: [] for value in positions}, 'partners': partners,
            'rows': (ColumnRows(kinds, points, partner, index)
                     if include_candidates else []),
            'omitted': False, 'include_candidates': include_candidates,
            'deferred': True}


def _output_index(array, child, kept, edge_ranges):
    """Resolve the recorded compartment of every contact, as the walk does."""
    if not edge_ranges:
        return array['index'].astype(np.int64)
    fraction = array['fraction']
    starts = np.zeros(len(array), dtype=np.int64)
    counts = np.ones(len(array), dtype=np.int64)
    matched = np.zeros(len(array), dtype=bool)
    for edge, (start, count) in edge_ranges.items():
        mask = child == edge
        starts[mask] = start
        counts[mask] = count
        matched |= mask
    if np.any(kept & ~matched):
        raise ValueError('Missing verified output position for remeshed cell')
    selected = fraction[kept]
    if not np.isfinite(selected).all() or (selected < 0).any() or (selected > 1).any():
        raise ValueError('Missing verified output position for remeshed cell')
    return starts + np.minimum((fraction * counts).astype(np.int64), counts - 1)


def _ordered_unique(values):
    """Return the distinct values in order of first appearance."""
    if not len(values):
        return []
    distinct, first = np.unique(values, return_index=True)
    return [int(value) for value in distinct[np.argsort(first, kind='stable')]]


class DeferredPartners:
    """Partner multiplicities computed per compartment, on first ask.

    The plan grouped every recorded compartment up front, but the renderer only
    asks for the compartments that crossed the threshold and a silenced cell
    crosses nothing: measured over 4 000 real cells the grouping was 60 % of the
    plan walk (1.11 s of 1.84 s) and nearly all of it was discarded. Grouping
    one compartment costs a pass over its own contacts, so the eager total stays
    the same and only the parts that are actually read get paid for.
    """

    __slots__ = ("_index", "_partner", "_cache")

    def __init__(self, index, partner):
        self._index = index
        self._partner = partner
        self._cache = {}

    def get(self, key, default=None):
        found = self[key]
        return default if found is None else found

    def __getitem__(self, key):
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        values = self._partner[self._index == key]
        if not len(values):
            return None
        unique, tally = np.unique(values, return_counts=True)
        counts = {int(value): int(count) for value, count in zip(unique, tally)}
        self._cache[key] = counts
        return counts

    def items(self):
        for value in np.unique(self._index).tolist():
            yield int(value), self[int(value)]

    def __len__(self):
        return int(len(np.unique(self._index)))

    def __iter__(self):
        return iter(np.unique(self._index).tolist())

    def __eq__(self, other):
        if isinstance(other, DeferredPartners):
            other = dict(other.items())
        return dict(self.items()) == other

    def __repr__(self):
        return f"DeferredPartners({len(self)} compartments)"


def _partner_counts(index, partner):
    """Group multiplicities by compartment, preserving first-appearance order."""
    if not len(index):
        return {}
    order = np.lexsort((partner, index))
    sorted_index, sorted_partner = index[order], partner[order]
    breaks = np.flatnonzero(np.diff(sorted_index)) + 1
    counts = {}
    for compartment, values in zip(np.split(sorted_index, breaks),
                                   np.split(sorted_partner, breaks)):
        unique, tally = np.unique(values, return_counts=True)
        counts[int(compartment[0])] = {int(value): int(count)
                                       for value, count in zip(unique, tally)}
    return counts


def _conflicting_duplicates(partner, point, index):
    """Report a shared presynaptic coordinate mapped to two compartments."""
    if len(partner) < 2:
        return False
    order = np.lexsort((point[:, 2], point[:, 1], point[:, 0], partner))
    ordered_partner = partner[order]
    ordered_point = point[order]
    resolved = index[order]
    same = ((np.diff(ordered_partner) == 0)
            & (np.diff(ordered_point[:, 0]) == 0)
            & (np.diff(ordered_point[:, 1]) == 0)
            & (np.diff(ordered_point[:, 2]) == 0))
    return bool(np.any(same & (np.diff(resolved) != 0)))