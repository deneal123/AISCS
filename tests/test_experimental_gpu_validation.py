import pytest

from service.infrastructure.stimulation.experimental_gpu.validation import (
    require_valid_voltage_ranges,
)


def test_voltage_range_flags_reject_only_flagged_cells():
    require_valid_voltage_ranges([0, 0], ['a', 'b'])
    with pytest.raises(ValueError, match='cells: b'):
        require_valid_voltage_ranges([0, 1], ['a', 'b'])


@pytest.mark.parametrize(('flags', 'cells'), [([], []), ([0], []), ([2], ['a'])])
def test_voltage_range_flags_reject_malformed_batch(flags, cells):
    with pytest.raises(ValueError):
        require_valid_voltage_ranges(flags, cells)
