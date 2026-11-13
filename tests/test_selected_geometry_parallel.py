import threading
from pathlib import Path

import pytest

from service.infrastructure.stimulation.geometry_cache import selected_chunk
from service.infrastructure.stimulation.geometry_cache.selected_parallel import iter_decoded_chunks


def test_parallel_decoding_preserves_order_and_bounds_inflight_work(monkeypatch):
    second_started = threading.Event()
    active = 0
    maximum = 0
    lock = threading.Lock()

    def read(path, descriptor, *, audited_sources, wanted):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            index = int(descriptor['name'])
            if index == 0:
                assert second_started.wait(5)
            elif index == 1:
                second_started.set()
            return [index]
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(selected_chunk, 'read_selected_chunk', read)
    chunks = [{'name': str(index)} for index in range(5)]
    actual = list(iter_decoded_chunks(Path('.'), chunks, sources={}, wanted=set(),
                                      selective=True, workers=2))
    assert actual == [[0], [1], [2], [3], [4]]
    assert maximum == 2
    assert not any(t.name.startswith('geometry-chunk') for t in threading.enumerate())


def test_parallel_failure_propagates_and_workers_are_joined(monkeypatch):
    def read(path, descriptor, *, audited_sources, wanted):
        if descriptor['name'] == 'bad':
            raise ValueError('invalid chunk checksum')
        return [descriptor['name']]

    monkeypatch.setattr(selected_chunk, 'read_selected_chunk', read)
    iterator = iter_decoded_chunks(Path('.'), [{'name': 'ok'}, {'name': 'bad'}],
                                   sources={}, wanted=set(), selective=True, workers=2)
    assert next(iterator) == ['ok']
    with pytest.raises(ValueError, match='checksum'):
        next(iterator)
    assert not any(t.name.startswith('geometry-chunk') for t in threading.enumerate())


def test_closing_parallel_iterator_joins_its_threads(monkeypatch):
    monkeypatch.setattr(selected_chunk, 'read_selected_chunk',
                        lambda path, descriptor, **kwargs: [descriptor['name']])
    iterator = iter_decoded_chunks(Path('.'), [{'name': str(i)} for i in range(5)],
                                   sources={}, wanted=set(), selective=True, workers=2)
    assert next(iterator) == ['0']
    iterator.close()
    assert not any(t.name.startswith('geometry-chunk') for t in threading.enumerate())


@pytest.mark.parametrize('workers', [0, 9, True, 1.5])
def test_invalid_parallelism_is_rejected(workers):
    with pytest.raises(ValueError, match='concurrency'):
        list(iter_decoded_chunks(Path('.'), [], sources={}, wanted=set(),
                                 selective=True, workers=workers))
