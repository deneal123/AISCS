from dataclasses import dataclass

import pytest

from service.application.population.bulk_numerical_identity import numerical_inputs_sha256


@dataclass
class Params:
    current_na: float


def test_identity_changes_with_numerical_inputs_and_rejects_nan():
    inputs = dict(params=Params(-300.), stimulus=[0., 1.], time_ms=[0., .05],
                  rate_table=[[1., 2.]], expected_ids=[1, 2], electrode_um=[1, 2, 3],
                  reference_um=[4, 5, 6], conductivity_s_m=.3, clearance_um=1.)
    value = numerical_inputs_sha256(**inputs)
    assert len(value) == 64 and value == numerical_inputs_sha256(**inputs)
    assert value != numerical_inputs_sha256(**{**inputs, 'stimulus': [0., .5]})
    assert value != numerical_inputs_sha256(**{**inputs, 'expected_ids': [2, 1]})
    with pytest.raises(ValueError):
        numerical_inputs_sha256(**{**inputs, 'stimulus': [0., float('nan')]})
