import pytest
from pydantic import ValidationError

from service.domain.contracts.population_target_contract import PopulationTargetConfig


def valid():
    return {'graph_manifest_sha256': 'a' * 64, 'source_package_sha256': 'b' * 64,
            'source_manifest_sha256': 'c' * 64, 'target_id': 20, 'source_ids': [10, 11],
            'duration_ms': 10, 'max_target_distance_um': 2., 'max_events': 100,
            'synapses': [{'delay_ms': 1., 'weight_us': .001, 'tau1_ms': .2, 'tau2_ms': 2.,
                          'reversal_mv': 0.}] * 2}


def test_target_contract_requires_explicit_bounded_parameters():
    config = PopulationTargetConfig.model_validate(valid())
    assert len(config.digest()) == 64
    assert config.schedules()[0]['duration_ms'] == 10
    assert 'timing_mode' not in config.model_dump(mode='json')
    upper = PopulationTargetConfig.model_validate({**valid(), 'timing_mode': 'upper_bound'})
    assert upper.digest() != config.digest()
    assert upper.model_dump(mode='json')['timing_mode'] == 'upper_bound'
    lower = PopulationTargetConfig.model_validate({**valid(), 'timing_mode': 'lower_bound'})
    assert lower.digest() not in (config.digest(), upper.digest())
    for changed in ({'source_ids': [10, 10]}, {'target_id': 10}, {'source_ids': [True, 11]},
                    {'synapses': [valid()['synapses'][0]]}, {'max_events': 1_000_001},
                    {'source_package_sha256': 'wrong'}, {'duration_ms': 10.5},
                    {'timing_mode': 'exact'}):
        with pytest.raises(ValidationError):
            PopulationTargetConfig.model_validate({**valid(), **changed})
