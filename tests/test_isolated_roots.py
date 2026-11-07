import numpy as np
import pytest

from service.infrastructure.stimulation.isolated_roots import (
    validate_isolated_root_arrays,
    validate_isolated_roots,
)


def test_isolated_root_radius_is_included_in_contact_clearance():
    swc = "1 1 0 0 0 125 -1\n2 1 12500 0 0 125 -1\n3 3 13750 0 0 125 2\n"
    # Source is 1.5 µm from an isolated vertex with radius 1 µm.
    with pytest.raises(ValueError, match="isolated"):
        validate_isolated_roots(swc, [[1.5, 0, 0], [200, 0, 0]], 1)
    validate_isolated_roots(swc, [[3, 0, 0], [200, 0, 0]], 1)


def test_connected_root_is_handled_by_segment_clearance():
    swc = "1 1 0 0 0 125 -1\n2 3 1250 0 0 125 1\n"
    validate_isolated_roots(swc, [[1, 0, 0], [200, 0, 0]], 1)


def test_array_check_matches_original_for_isolated_and_connected_roots():
    swc = "1 1 0 0 0 125 -1\n2 1 12500 0 0 125 -1\n3 3 13750 0 0 125 2\n"
    points = np.array([[0., 0., 0.], [100., 0., 0.], [110., 0., 0.]])
    radii, parents = np.ones(3), np.array([-1, -1, 1])
    for coordinate in np.linspace(-4, 4, 33):
        contacts = [[coordinate, 0., 0.], [200., 0., 0.]]
        results = []
        operations = (
            lambda c=contacts: validate_isolated_roots(swc, c, 1),
            lambda c=contacts: validate_isolated_root_arrays(points, radii, parents, c, 1),
        )
        for operation in operations:
            try:
                operation()
            except ValueError:
                results.append(False)
            else:
                results.append(True)
        assert results[0] == results[1]
