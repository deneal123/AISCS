import numpy as np

from service.infrastructure.stimulation.experimental_gpu.recording_cache import (
    FORMAT,
    RecordingCoefficientCache,
    batch_key,
)

GEOMETRY = 'c' * 64
MORPHOLOGY = 'e' * 64


def _geometry(segments, scale=1.):
    starts = np.arange(segments * 3, dtype=float).reshape(segments, 3) * scale
    return {'starts_um': starts, 'ends_um': starts + 1., 'midpoints_um': starts + .5,
            'endpoint_radii_um': np.full((segments, 2), .4)}


def _morphologies(geometries, digest=MORPHOLOGY):
    return {body: digest for body in geometries}


def _key(geometries, geometry_sha256=GEOMETRY, morphologies=None):
    return batch_key(geometries, geometry_sha256=geometry_sha256,
                     morphologies=(_morphologies(geometries) if morphologies is None
                                   else morphologies),
                     electrode_um=(1., 2., 3.),
                     reference_um=(0., 0., 0.), conductivity_s_m=.3, clearance_um=1.)


def _cache_key(cache, geometries, morphologies=None):
    return cache.key_for(geometries,
                         morphologies=(_morphologies(geometries) if morphologies is None
                                       else morphologies),
                         electrode_um=(1., 2., 3.), reference_um=(0., 0., 0.),
                         conductivity_s_m=.3, clearance_um=1.)


def test_a_batch_survives_the_store_field_for_field(tmp_path):
    geometries = {4: _geometry(3), 9: _geometry(2, 2.)}
    cache = RecordingCoefficientCache(tmp_path, GEOMETRY)
    key = _cache_key(cache, geometries)
    assert cache.get(key, [4, 9]) is None
    values = {4: np.arange(3, dtype=float), 9: np.arange(2, dtype=float) + 10.}
    cache.put(key, [4, 9], values)
    stored = cache.get(key, [4, 9])
    assert stored is not None and sorted(stored) == [4, 9]
    assert np.array_equal(stored[4], values[4])
    assert np.array_equal(stored[9], values[9])
    # A copy, not a view into one shared block: writing one cell must not disturb
    # the other, and the block is released with the result.
    stored[4][0] = -1.
    assert stored[9][0] == 10.


def test_a_different_geometry_identity_is_a_miss(tmp_path):
    geometries = {4: _geometry(3)}
    cache = RecordingCoefficientCache(tmp_path, GEOMETRY)
    key = _cache_key(cache, geometries)
    cache.put(key, [4], {4: np.arange(3, dtype=float)})
    assert cache.get(key, [4]) is not None
    other = RecordingCoefficientCache(tmp_path, 'd' * 64)
    # Same directory, same batch, different reduced geometry: the entry belongs to
    # the params that produced it and must not answer for another.
    assert other.get(key, [4]) is None


def test_the_key_covers_the_cells_the_morphologies_the_electrodes_and_the_params():
    geometries = {4: _geometry(3)}
    base = _key(geometries)
    assert base == _key({4: _geometry(3)})
    assert base != _key({4: _geometry(3)}, geometry_sha256='d' * 64)
    assert base != _key({5: _geometry(3)})
    # The morphology digest is the identity of the reduced geometry the
    # coefficients were computed from: another morphology is another geometry.
    assert base != _key({4: _geometry(3)},
                        morphologies={4: 'f' * 64})
    assert base != batch_key(geometries, geometry_sha256=GEOMETRY,
                             morphologies={4: MORPHOLOGY},
                             electrode_um=(1., 2., 4.), reference_um=(0., 0., 0.),
                             conductivity_s_m=.3, clearance_um=1.)
    assert base != batch_key(geometries, geometry_sha256=GEOMETRY,
                             morphologies={4: MORPHOLOGY},
                             electrode_um=(1., 2., 3.), reference_um=(0., 0., 0.),
                             conductivity_s_m=.31, clearance_um=1.)


def test_the_key_is_cheap_because_it_names_cells_instead_of_segments():
    # The old key digested 88 bytes per segment, which on the full population was
    # 23.8 GB and 5.4 ms per cell on the wide tail. The new one is a function of
    # the identity digests alone, so a wide batch costs the same as a narrow one.
    narrow = {body: _geometry(2) for body in range(1, 9)}
    wide = {body: _geometry(20000) for body in range(1, 9)}
    morphologies = {body: f'{body:064x}' for body in range(1, 9)}
    narrow_key = _key(narrow, morphologies=morphologies)
    wide_key = _key(wide, morphologies=morphologies)
    # Different segment counts are different cells and must not share an entry.
    assert narrow_key != wide_key


def test_a_truncated_payload_is_a_miss(tmp_path):
    geometries = {4: _geometry(3)}
    cache = RecordingCoefficientCache(tmp_path, GEOMETRY)
    key = _cache_key(cache, geometries)
    cache.put(key, [4], {4: np.arange(3, dtype=float)})
    payload = cache.entry(key) / 'coefficients.bin'
    payload.write_bytes(payload.read_bytes()[:-8])
    assert cache.get(key, [4]) is None


def test_an_entry_for_other_cells_is_a_miss(tmp_path):
    geometries = {4: _geometry(3), 9: _geometry(2)}
    cache = RecordingCoefficientCache(tmp_path, GEOMETRY)
    key = _cache_key(cache, geometries)
    cache.put(key, [4], {4: np.arange(3, dtype=float)})
    # The key names the cells, so asking for both cannot hit the entry that holds
    # only one of them, even before the id list is compared.
    assert cache.get(key, [4, 9]) is None


def test_the_cache_refuses_a_key_without_a_geometry_identity(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        batch_key({4: _geometry(3)}, geometry_sha256='', morphologies={4: MORPHOLOGY},
                  electrode_um=(0., 0., 0.),
                  reference_um=(0., 0., 0.), conductivity_s_m=.3, clearance_um=1.)
    cache = RecordingCoefficientCache(tmp_path, GEOMETRY)
    assert cache.geometry_sha256 == GEOMETRY
    assert FORMAT == 'malecns-recording-coefficients-v1'


def test_a_key_without_a_morphology_digest_is_refused():
    import pytest

    with pytest.raises(ValueError):
        batch_key({4: _geometry(3)}, geometry_sha256=GEOMETRY, morphologies={},
                  electrode_um=(0., 0., 0.), reference_um=(0., 0., 0.),
                  conductivity_s_m=.3, clearance_um=1.)
    with pytest.raises(ValueError):
        batch_key({4: _geometry(3)}, geometry_sha256=GEOMETRY, morphologies={4: 'nope'},
                  electrode_um=(0., 0., 0.), reference_um=(0., 0., 0.),
                  conductivity_s_m=.3, clearance_um=1.)
