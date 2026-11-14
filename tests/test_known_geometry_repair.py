import pytest

from service.infrastructure.stimulation.experimental_gpu.known_geometry_repair import (
    KNOWN_SOURCE_SHA256,
    known_zero_edge_replacement,
)


def test_only_verified_known_geometry_can_be_replaced(monkeypatch):
    module = 'service.infrastructure.stimulation.experimental_gpu.known_geometry_repair.'
    monkeypatch.setattr(module + 'read_skeleton',
                        lambda body, directories, expected_sha256: {'swc': 'verified'})
    monkeypatch.setattr(module + 'prepare_contracted_cell',
                        lambda raw, **kwargs: (raw, kwargs))
    replace = known_zero_edge_replacement(['registered'], 'params')
    raw, receipt = replace(842998, 7, KNOWN_SOURCE_SHA256)
    assert raw == b'verified'
    assert receipt['source_sha256'] == KNOWN_SOURCE_SHA256
    assert (receipt['parent_id'], receipt['child_id']) == (75, 76)
    with pytest.raises(ValueError, match='Unsupported'):
        replace(842998, 8, 'a' * 64)
    with pytest.raises(ValueError, match='Unsupported'):
        replace(42, 7, 'a' * 64)


def test_missing_source_fails_when_handler_is_created(monkeypatch):
    def missing(*_args, **_kwargs):
        raise FileNotFoundError('verified source missing')

    monkeypatch.setattr(
        'service.infrastructure.stimulation.experimental_gpu.known_geometry_repair.read_skeleton',
        missing)
    with pytest.raises(FileNotFoundError, match='verified source missing'):
        known_zero_edge_replacement([], 'params')
