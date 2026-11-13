from service.infrastructure.stimulation.geometry_cache import producer_compatibility as policy


def test_exact_reviewed_tuple_only():
    manifest, old, current = next(iter(policy.REVIEWED_PRODUCERS))
    assert policy.producer_is_compatible(manifest, old, current)
    assert policy.producer_is_compatible('other', current, current)
    assert not policy.producer_is_compatible('other', old, current)
    assert not policy.producer_is_compatible(manifest, 'other', current)
    assert not policy.producer_is_compatible(manifest, old, 'other')
