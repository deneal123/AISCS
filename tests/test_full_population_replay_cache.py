import hashlib
import json

import numpy as np
import pytest

from service.application.feedback.replay_cache import FORMAT, ReplayPassCache, pass_key

OPTIONS = {'dt_ms': .05, 'threshold_mv': -20., 'segment_budget': 3000000,
           'expected_ids': [1, 2], 'params': object(), 'time_ms': np.arange(3) * .05,
           'metadata_factory': lambda cells: cells, 'event_path': '/tmp/x.jsonl'}


def _identity(**overrides):
    values = {'graph_sha256': 'a' * 64, 'configuration_sha256': 'b' * 64,
              'baseline_sha256': 'c' * 64, 'replay_options': OPTIONS}
    values.update(overrides)
    return values


def _receipt(tmp_path, trace=(0., 1., 0.), activity=(0, 3, 2)):
    archive = tmp_path / 'events.jsonl'
    archive.write_text('{"1": {"edge_events": []}}\n', encoding='utf8')
    # A real receipt always carries the digest of the archive it published;
    # the cache re-verifies it, so a fabricated digest is legitimately a miss.
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    counts = np.asarray(activity, dtype=np.int64)
    return {'event_sha256': digest, 'neural_uv': np.asarray(trace, dtype=float),
            'activity': counts, 'spikes': int(counts.sum()),
            'cells': 2, 'solver_kernels': {'accelerated_cell_major': 1, 'generic': 0,
                                           'batches': 1},
            'endpoint_relocation': None}


def test_pass_key_ignores_callbacks_and_paths_but_not_arithmetic():
    base = pass_key('full_active', np.zeros(4), **_identity())
    assert base == pass_key('full_active', np.zeros(4), **_identity(
        replay_options={**OPTIONS, 'batch_progress': print, 'event_path': '/other'}))
    assert base != pass_key('full_active', np.zeros(4), **_identity(
        replay_options={**OPTIONS, 'threshold_mv': -19.}))
    assert base != pass_key('full_active', np.ones(4), **_identity())
    assert base != pass_key('full_control', np.zeros(4), **_identity())


def test_pass_key_rejects_unsupported_phase_and_nonfinite_stimulus():
    with pytest.raises(ValueError):
        pass_key('full_feedback', np.zeros(4), **_identity())
    with pytest.raises(ValueError):
        pass_key('full_active', np.asarray([0., np.nan]), **_identity())


def test_cache_round_trip_restores_archive_and_trace(tmp_path):
    cache, key = ReplayPassCache(tmp_path / 'cache'), pass_key('full_active', np.zeros(4),
                                                               **_identity())
    assert cache.load(key, tmp_path / 'target.jsonl') is None
    cache.save(key, tmp_path / 'events.jsonl', _receipt(tmp_path), extra={'note': 1})
    restored = cache.load(key, tmp_path / 'target.jsonl')
    assert restored['event_sha256'] == hashlib.sha256(
        (tmp_path / 'events.jsonl').read_bytes()).hexdigest() and restored['cells'] == 2
    assert np.array_equal(restored['neural_uv'], np.asarray([0., 1., 0.]))
    assert restored['extra'] == {'note': 1}
    assert (tmp_path / 'target.jsonl').read_text(encoding='utf8').startswith('{"1"')


def test_corrupted_or_foreign_entry_is_a_miss(tmp_path):
    cache, key = ReplayPassCache(tmp_path / 'cache'), pass_key('full_active', np.zeros(4),
                                                               **_identity())
    cache.save(key, tmp_path / 'events.jsonl', _receipt(tmp_path))
    entry = cache.directory / key[:2] / key
    (entry / 'events.jsonl').write_text('tampered\n', encoding='utf8')
    assert cache.load(key, tmp_path / 'target.jsonl') is None
    (entry / 'meta.json').write_text(json.dumps({'format': FORMAT, 'key': 'e' * 64}),
                                     encoding='utf8')
    assert cache.load(key, tmp_path / 'target.jsonl') is None
    assert not (entry.parent.iterdir().__next__().name.startswith('.'))


def test_saving_again_replaces_the_previous_entry(tmp_path):
    cache, key = ReplayPassCache(tmp_path / 'cache'), pass_key('full_active', np.zeros(4),
                                                               **_identity())
    cache.save(key, tmp_path / 'events.jsonl', _receipt(tmp_path))
    cache.save(key, tmp_path / 'events.jsonl', _receipt(tmp_path, trace=(0., 2., 0.)))
    restored = cache.load(key, tmp_path / 'target.jsonl')
    assert np.array_equal(restored['neural_uv'], np.asarray([0., 2., 0.]))
    assert [path.name for path in cache.directory.iterdir()] == [key[:2]]


def test_restored_entry_carries_the_spike_count_beside_the_trace(tmp_path):
    cache, key = ReplayPassCache(tmp_path / 'cache'), pass_key('full_active', np.zeros(4),
                                                               **_identity())
    cache.save(key, tmp_path / 'events.jsonl', _receipt(tmp_path, activity=(0, 7, 4)))
    restored = cache.load(key, tmp_path / 'target.jsonl')
    assert np.array_equal(restored['activity'], np.asarray([0, 7, 4]))
    assert restored['spikes'] == 11


def test_a_receipt_without_the_spike_count_is_refused(tmp_path):
    cache, key = ReplayPassCache(tmp_path / 'cache'), pass_key('full_active', np.zeros(4),
                                                               **_identity())
    receipt = _receipt(tmp_path)
    del receipt['activity']
    with pytest.raises(ValueError, match='activity'):
        cache.save(key, tmp_path / 'events.jsonl', receipt)
    assert not cache.directory.exists()


def test_a_tampered_spike_count_is_a_miss(tmp_path):
    cache, key = ReplayPassCache(tmp_path / 'cache'), pass_key('full_active', np.zeros(4),
                                                               **_identity())
    cache.save(key, tmp_path / 'events.jsonl', _receipt(tmp_path))
    entry = cache.directory / key[:2] / key
    # Same shape, different counts: the totals recorded in the entry no longer
    # describe the file, so the entry must not be restored.
    with (entry / 'activity.npy').open('wb') as stream:
        np.save(stream, np.asarray([0, 1, 0], dtype=np.int64))
    assert cache.load(key, tmp_path / 'target.jsonl') is None
