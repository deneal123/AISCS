import pytest

from service.infrastructure.stimulation.experimental_gpu.prepare import prepare_registered_cell


@pytest.mark.parametrize('digest', [None, '', 'X' * 64, '0' * 63])
def test_prepare_requires_verified_digest_before_reading_morphology(digest):
    with pytest.raises(ValueError, match='SHA-256'):
        prepare_registered_cell(1, [], expected_sha256=digest, source_um=[0, 0, 0],
                                return_um=[1, 0, 0], current_na=1., conductivity_s_m=.3,
                                clearance_um=1., events=[], duration_ms=10.)
