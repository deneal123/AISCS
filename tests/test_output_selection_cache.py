"""The output-selection table: one answer per preparation, reused by every pass."""


import numpy as np

from service.application.feedback.output_selection import OutputSelection, open_output_selection
from service.infrastructure.stimulation.experimental_gpu.narrow_cache import params_identity
from service.infrastructure.stimulation.experimental_gpu.selection_cache import (
    HAS_CANDIDATES,
    HAS_PLACEHOLDERS,
    SelectionCache,
    preparation_identity,
    selection_identity,
)

MANIFEST = {'chunks': [{'name': 'chunk-000000.bin', 'sha256': 'a' * 64},
                       {'name': 'chunk-000001.bin', 'sha256': 'b' * 64}],
            'graph_sha256': 'c' * 64, 'source_index_sha256': 'd' * 64, 'vertices': 4096}
def _options(params=None):
    return {'params': params or PARAMS}


class _Params:
    """The physical inputs preparation consumes, as the production code sees them."""

    def __init__(self, **overrides):
        values = {'source_um': (1.0, 2.0, 3.0), 'return_um': (4.0, 5.0, 6.0),
                  'current_na': 100.0, 'conductivity_s_m': 0.3, 'clearance_um': 1.0,
                  'axial_resistivity': 100.0, 'capacitance': 1.0, 'nseg': 1.0}
        values.update(overrides)
        for name, value in values.items():
            setattr(self, name, value)


PARAMS = _Params()


def _identity(threshold=-20.0, distance=6.0, manifest=None, params=None):
    params = params or PARAMS
    return selection_identity(params_identity=params_identity(params), threshold_mv=threshold,
        duration_ms=10, max_distance_um=distance,
        preparation_sha256=preparation_identity(manifest or MANIFEST, params_identity(params)))


def test_a_stored_table_is_read_back_field_by_field(tmp_path):
    cache = SelectionCache(tmp_path, _identity())
    cache.store(np.asarray([101, 202], dtype=np.int64),
                np.asarray([0, 3, 4], dtype=np.int64),
                np.asarray([5, 6, 7, 8], dtype=np.int32),
                np.asarray([HAS_CANDIDATES, 0], dtype=np.uint8))
    reopened = SelectionCache(tmp_path, _identity())
    assert reopened.load() is True
    assert reopened.entry_for(101) == ([5, 6, 7], HAS_CANDIDATES)
    assert reopened.entry_for(202) == ([8], 0)
    # A cell nobody asked about has no entry, and the caller must then plan it.
    assert reopened.entry_for(303) is None


def test_a_table_built_for_another_threshold_is_not_read(tmp_path):
    SelectionCache(tmp_path, _identity()).store(np.asarray([101]), np.asarray([0, 1]),
        np.asarray([5], dtype=np.int32), np.asarray([1], dtype=np.uint8))
    other = SelectionCache(tmp_path, _identity(threshold=-30.0))
    assert other.load() is False


def test_a_table_built_for_another_preparation_is_not_read(tmp_path):
    SelectionCache(tmp_path, _identity()).store(np.asarray([101]), np.asarray([0, 1]),
        np.asarray([5], dtype=np.int32), np.asarray([1], dtype=np.uint8))
    moved = {'chunks': [{'name': 'chunk-000000.bin', 'sha256': 'e' * 64},
                        {'name': 'chunk-000001.bin', 'sha256': 'b' * 64}],
             'graph_sha256': 'c' * 64, 'source_index_sha256': 'd' * 64, 'vertices': 4096}
    assert SelectionCache(tmp_path, _identity(manifest=moved)).load() is False
    assert SelectionCache(tmp_path, _identity(params=_Params(nseg=2.0))).load() is False


def test_a_damaged_table_is_refused_rather_than_half_read(tmp_path):
    identity = _identity()
    SelectionCache(tmp_path, identity).store(np.asarray([101]), np.asarray([0, 1]),
        np.asarray([5], dtype=np.int32), np.asarray([1], dtype=np.uint8))
    data = tmp_path / identity / 'selection.npz'
    raw = bytearray(data.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    data.write_bytes(bytes(raw))
    assert SelectionCache(tmp_path, identity).load() is False


def test_the_identity_separates_distance_cuts_and_bad_input():
    assert _identity(distance=6.0) != _identity(distance=4.0)
    for bad in ({'threshold': None}, {'threshold': True}):
        try:
            _identity(**bad)
        except ValueError:
            continue
        raise AssertionError('invalid identity was accepted')


def test_a_partial_pass_does_not_publish_its_table(tmp_path):
    handle = OutputSelection(SelectionCache(tmp_path, _identity()))
    handle.expect(3)
    handle.record(101, [5, 6], placeholders=False)
    handle.record(202, [], placeholders=False)
    assert handle.commit() is None
    assert SelectionCache(tmp_path, _identity()).load() is False


def test_a_complete_pass_publishes_and_the_next_one_reads(tmp_path):
    handle = OutputSelection(SelectionCache(tmp_path, _identity()))
    handle.expect(2)
    handle.record(101, [5, 6], placeholders=False)
    handle.record(202, [7], placeholders=True)
    header = handle.commit()
    assert header['cells'] == 2 and header['compartments'] == 3

    reopened = OutputSelection(SelectionCache(tmp_path, _identity()))
    assert reopened.loaded is True
    assert reopened.entry_for(101) == ([5, 6], HAS_CANDIDATES)
    assert reopened.entry_for(202) == ([7], HAS_CANDIDATES | HAS_PLACEHOLDERS)
    assert reopened.receipt()['hits'] == 2


def test_an_incomplete_pass_refuses_to_publish(tmp_path):
    handle = OutputSelection(SelectionCache(tmp_path, _identity()))
    handle.expect(2)
    handle.record(101, [5], placeholders=False)
    handle.note_incomplete()
    assert handle.commit() is None


def test_open_output_selection_names_the_question_the_pass_asks(tmp_path):
    options = _options()
    first = open_output_selection(MANIFEST, options, directory=tmp_path,
        threshold_mv=-20.0, duration_ms=10, max_source_distance_um=6.0)
    moved = open_output_selection(MANIFEST, options, directory=tmp_path,
        threshold_mv=-20.0, duration_ms=10, max_source_distance_um=4.0)
    assert first.identity != moved.identity
    assert first.loaded is False
