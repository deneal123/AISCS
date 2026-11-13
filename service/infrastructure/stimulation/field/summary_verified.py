"""Verify field-summary identity and load explicit per-neuron descriptors."""

import numpy as np

from service.infrastructure.connectome.dataset import digest
from service.infrastructure.stimulation.field.summary_audit import audit, failure_category


def verified_descriptors(path, ids, graph_hash, *, allow_partial_geometry=False,
                         allow_missing_curvature=False, allow_contact_exclusion=False,
                         expected_configuration=None):
    """Check the full chain, ordered identities and file stability before use."""
    if any(type(value) is not bool for value in (
        allow_partial_geometry, allow_missing_curvature, allow_contact_exclusion,
    )):
        raise ValueError('Invalid exclusion policy')
    before = digest(path)
    descriptors = np.empty(len(ids), dtype=np.float64)
    excluded = []
    contact_excluded = []
    invalid = False

    def collect(index, row):
        nonlocal invalid
        status = row['status']
        if status == 'invalid_geometry_or_field':
            if (allow_contact_exclusion
                    and failure_category(status, row.get('reason')) == 'contact_exclusion'):
                contact_excluded.append(row['body_id'])
            else:
                invalid = True
            # Unknown direct field is explicitly excluded, not a biological estimate.
            descriptors[index] = 0.0
            return
        if (status == 'source_missing'
                or (status == 'partial_geometry' and not allow_partial_geometry)):
            invalid = True
            descriptors[index] = 0.0
            return
        value = row.get('max_abs_curvature_signed_mv_per_um2')
        if value is None:
            if allow_missing_curvature:
                excluded.append(row['body_id'])
            else:
                invalid = True
            descriptors[index] = 0.0
        else:
            descriptors[index] = value

    report = audit(path, ids, graph_hash=graph_hash, on_row=collect)
    if expected_configuration is not None and report['configuration'] != expected_configuration:
        raise ValueError('Field configuration does not match requested contacts or current')
    allowed = {'ok', 'partial_geometry'} if allow_partial_geometry else {'ok'}
    if allow_contact_exclusion:
        allowed.add('invalid_geometry_or_field')
    if not report['complete'] or set(report['statuses']) - allowed or invalid:
        raise ValueError('Field summary is incomplete or contains failed geometry')
    if digest(path) != before:
        raise ValueError('Field summary changed while reading')
    return descriptors, {'file_sha256': before, 'field_audit': report,
                         'allow_partial_geometry': allow_partial_geometry,
                         'excluded_from_direct_field': excluded,
                         'excluded_contact_intersections': contact_excluded}
