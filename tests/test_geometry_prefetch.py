import threading

import pytest

from service.infrastructure.stimulation.geometry_prefetch import prefetch


def test_prefetch_keeps_order_and_reads_next_chunk_while_current_is_consumed():
    entered = threading.Event()
    release = threading.Event()

    def chunks():
        yield 'first'
        entered.set()
        assert release.wait(3)
        yield 'second'

    items = prefetch(chunks())
    try:
        assert next(items) == 'first'
        assert entered.wait(3)
        release.set()
        assert list(items) == ['second']
    finally:
        release.set()
        items.close()


def test_prefetch_does_not_hide_errors_or_discard_completed_values():
    def chunks():
        yield 1
        raise ValueError('broken chunk')

    items = prefetch(chunks())
    assert next(items) == 1
    with pytest.raises(ValueError, match='broken chunk'):
        next(items)


def test_prefetch_closes_source_on_early_consumer_exit():
    closed = []

    def chunks():
        try:
            yield 1
            yield 2
            yield 3
        finally:
            closed.append(True)

    items = prefetch(chunks())
    assert next(items) == 1
    items.close()
    assert closed == [True]
