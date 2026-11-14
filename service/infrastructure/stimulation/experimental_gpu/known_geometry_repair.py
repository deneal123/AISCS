"""Explicitly opt in to a provenance-recorded correction of one source edge."""

from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.experimental_gpu.derived_geometry import (
    prepare_contracted_cell,
)

KNOWN_SOURCE_SHA256 = 'eaf2cc8e8d61313b2928e5b365fadc7876ec6d48ba0838c969ce865a00c833d9'


def known_zero_edge_identity(directories):
    """Recompute source and derived hashes without assuming electrical equivalence."""
    from service.infrastructure.stimulation.zero_edge_transform import contract_zero_edge

    source = read_skeleton(842998, directories, expected_sha256=KNOWN_SOURCE_SHA256)
    _, receipt = contract_zero_edge(source['swc'].encode('utf8'),
        expected_sha256=KNOWN_SOURCE_SHA256, parent_id=75, child_id=76)
    return receipt


def known_zero_edge_replacement(directories, params):
    """Return a strict 842998/75→76 handler; all other defects remain errors."""
    source = read_skeleton(842998, directories, expected_sha256=KNOWN_SOURCE_SHA256)
    raw = source['swc'].encode('utf8')

    def replace(body, code, source_sha256):
        if body != 842998 or code != 7 or source_sha256 != KNOWN_SOURCE_SHA256:
            raise ValueError('Unsupported morphology defect')
        return prepare_contracted_cell(raw, source_sha256=source_sha256,
                                       body_id=body, parent_id=75, child_id=76, params=params)
    return replace
