"""Verify field-summary identity and load explicit per-neuron descriptors."""

import json

from service.infrastructure.connectome.dataset import digest
from service.infrastructure.connectome.field_proxy import descriptor_from_rows
from service.infrastructure.stimulation.field_summary_audit import audit, failure_category


def verified_descriptors(path, ids, graph_hash, *, allow_partial_geometry=False,
                         allow_missing_curvature=False, allow_contact_exclusion=False,
                         expected_configuration=None):
    """Check the full chain, ordered identities and file stability before use."""
    before = digest(path)
    report = audit(path, ids, graph_hash=graph_hash)
    if expected_configuration is not None and report['configuration'] != expected_configuration:
        raise ValueError('Field configuration does not match requested contacts or current')
    allowed = {'ok', 'partial_geometry'} if allow_partial_geometry else {'ok'}
    if allow_contact_exclusion:
        allowed.add('invalid_geometry_or_field')
    if not report['complete'] or set(report['statuses']) - allowed:
        raise ValueError('Field summary is incomplete or contains failed geometry')
    if type(allow_missing_curvature) is not bool or type(allow_contact_exclusion) is not bool:
        raise ValueError('Invalid exclusion policy')
    excluded = []
    contact_excluded = []
    with path.open(encoding='utf-8') as stream:
        next(stream)
        rows = (json.loads(line) for line in stream)

        def eligible():
            for row in rows:
                if row.get('kind') == 'footer':
                    continue
                if row.get('status') == 'invalid_geometry_or_field':
                    if (not allow_contact_exclusion
                            or failure_category(row['status'], row.get('reason'))
                            != 'contact_exclusion'):
                        raise ValueError('Field row has an unsupported geometry failure')
                    contact_excluded.append(row['body_id'])
                    # The model is undefined at the contact; omit direct input explicitly.
                    row = {**row, 'status': 'ok', 'max_abs_curvature_signed_mv_per_um2': 0.0}
                if row.get('max_abs_curvature_signed_mv_per_um2') is None and allow_missing_curvature:
                    excluded.append(row.get('body_id'))
                    # Exclude direct stimulation; this is not an estimate of coupling.
                    row = {**row, 'max_abs_curvature_signed_mv_per_um2': 0.0}
                yield row

        descriptors = descriptor_from_rows(ids, eligible(),
                                           allow_partial_geometry=allow_partial_geometry)
    if digest(path) != before:
        raise ValueError('Field summary changed while reading')
    return descriptors, {'file_sha256': before, 'field_audit': report,
                         'allow_partial_geometry': allow_partial_geometry,
                         'excluded_from_direct_field': excluded,
                         'excluded_contact_intersections': contact_excluded}
