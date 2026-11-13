import pytest

from service.infrastructure.stimulation.experimental_gpu.prepare_batches import (
    prepare_registered_batch,
)


def test_order_and_identity_checked(monkeypatch):
    module = 'service.infrastructure.stimulation.experimental_gpu.prepare_batches.'
    monkeypatch.setattr(module + 'prepare_registered_cell',
                        lambda body, directories, **kwargs: {'id': body, 'arg': kwargs['value']})
    requests = [{'body_id': 2, 'parameters': {'value': 7}},
                {'body_id': 1, 'parameters': {'value': 8}}]
    assert prepare_registered_batch(requests, [], workers=1) == [
        {'id': 2, 'arg': 7}, {'id': 1, 'arg': 8}]
    monkeypatch.setattr(module + 'prepare_registered_cell', lambda *_a, **_k: {'id': 99})
    with pytest.raises(ValueError, match='identity'):
        prepare_registered_batch(requests, [], workers=1)


def test_duplicate_cells_and_invalid_workers_rejected():
    request = {'body_id': 1, 'parameters': {}}
    with pytest.raises(ValueError, match='batch'):
        prepare_registered_batch([request, request], [], workers=1)
    with pytest.raises(ValueError, match='batch'):
        prepare_registered_batch([request], [], workers=0)
