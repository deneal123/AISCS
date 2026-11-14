"""Explicit preparation of a derived, single-zero-edge SWC geometry."""

import numpy as np

from service.infrastructure.stimulation.zero_edge_transform import contract_zero_edge

from .fast_cable import CACHE_RECORD, prepare_chunk
from .fast_prepare import cells_from_chunk


def prepare_contracted_cell(raw, *, source_sha256, body_id, parent_id, child_id, params):
    """Prepare an explicitly derived morphology; no equivalence is asserted."""
    if type(body_id) is not int or body_id <= 0:
        raise ValueError('Invalid derived cell ID')
    derived, receipt = contract_zero_edge(raw, expected_sha256=source_sha256,
                                          parent_id=parent_id, child_id=child_id)
    rows = [line.split() for line in derived.decode('utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
    indices = {int(row[0]): index for index, row in enumerate(rows)}
    records = np.array([
        tuple(float(value) * .008 for value in row[2:6])
        + (indices[int(row[6])] if int(row[6]) != -1 else -1, int(row[0]))
        for row in rows], dtype=CACHE_RECORD)
    prepared = prepare_chunk(records, np.array([0], dtype=np.int64),
                             np.array([len(records)], dtype=np.int64), params, bodies=[body_id],
                             store_bounds=True)
    cell = cells_from_chunk(prepared, sources={body_id: receipt['derived_sha256']})[0]
    return cell, receipt
