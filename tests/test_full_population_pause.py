"""Pause and resume tests for the full detailed-population experiment."""

import hashlib
from pathlib import Path

import numpy as np

import pytest

from service.application.feedback.event_archive import EventArchive
from service.application.feedback.pause import (
    FORMAT, PauseController, ReplayPaused, capture_state, clear, load,
)
from service.application.feedback.population_bulk_replay import (
    replay_bulk_feedback, replay_bulk_feedback_to_archive,
)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _archive(tmp_path, name, batches):
    path = tmp_path / name
    with EventArchive(path) as archive:
        for batch in batches:
            archive.write_batch(batch)
        archive.commit()
    return path


def _arguments():
    ids = [10, 20, 30, 40]
    return dict(metadata={'graph_sha256': 'a' * 64}, stimulus=np.zeros(4),
                rate_table={}, audited_sources={}, params=None, expected_ids=ids,
                events_by_target=lambda batch: {body: [] for body in batch},
                metadata_factory=lambda cells: {},
                time_ms=list(np.arange(4) * .05), threshold_mv=-20., duration_ms=.15,
                electrode_um=(0., 0., 0.), reference_um=(0., 0., 1.), conductivity_s_m=.3,
                clearance_um=1., segment_budget=10, output_budget_bytes=10)


class _Recording:
    def __init__(self, samples, resume=None):
        self.signal = np.zeros(samples) if resume is None else np.array(resume['signal'], float)
        self.completed = set() if resume is None else set(resume['done_ids'])
        # The receipt reports the coefficient cache, so a stand-in has to carry
        # the same counters the real recording does.
        self.coefficients = None
        self.coefficient_hits = 0
        self.coefficient_misses = 0
        self.coefficient_errors = 0
        self.activity = (np.zeros(samples, dtype=np.int64) if resume is None
                         else np.array(resume['activity'], np.int64)
                         if resume.get('activity') is not None
                         else np.zeros(samples, dtype=np.int64))

    def settled(self):
        return set(self.completed)


class _Collector:
    """Stand-in for the windowed collector: it only has to account for cells."""

    def __init__(self, expected_ids, *, resume=None, samples=4, **kwargs):
        self.recording = _Recording(samples, resume)
        # The receipt also reports the crossings the one-millisecond tick grid
        # could not carry, so the stand-in has to answer for them too.
        self.coincident_crossings = 0

    def factory(self, cells):
        self.recording.completed.update(int(body) for body in cells)
        self.recording.signal[0] += float(len(cells))
        return object()

    def finish(self):
        return self.recording.signal.copy()

    @property
    def activity(self):
        return self.recording.activity


def _stub_solver(batches):
    def solve_population(metadata, stimulus, rate_table, *, device_window_factory,
                         event_factory, resume=None, **kwargs):
        # The real producer drops a continued prefix before it reaches the
        # consumer, so the consumer never sees those batches at all.
        skip = 0 if resume is None else int(resume['batches'])
        for index, batch in enumerate(batches):
            if index < skip:
                continue
            device_window_factory(batch)
            event_factory(batch)
            yield list(batch), {'accelerated_cell_major': True, 'table_clamped_cell_ids': []}
    return solve_population


def test_checkpoint_round_trip_keeps_every_identity(tmp_path):
    archive = _archive(tmp_path, 'events.jsonl', [{'10': []}, {'20': []}])
    with EventArchive(tmp_path / 'live.jsonl', resume_from=archive) as live:
        live.write_batch({'30': []})
        controller = PauseController(tmp_path / 'pause')
        meta = controller.save(phase='full_active',
            capture=lambda state: capture_state(state, archive=live,
                signal=np.array([1., 2., 3., 4.]), done_ids={10, 20, 30},
                cells=3, batches=2))
    assert meta['format'] == FORMAT and meta['phase'] == 'full_active'
    restored = load(tmp_path / 'pause')
    assert restored['done_ids'] == {10, 20, 30} and restored['batches'] == 2
    np.testing.assert_array_equal(restored['signal'], [1., 2., 3., 4.])
    assert restored['archive_sha256'] == _digest(tmp_path / 'pause' / 'state' / 'events.jsonl')


def test_checkpoint_rejects_an_archive_that_changed_under_it(tmp_path):
    archive = _archive(tmp_path, 'events.jsonl', [{'10': []}])
    with EventArchive(tmp_path / 'live.jsonl', resume_from=archive) as live:
        PauseController(tmp_path / 'pause').save(phase='full_active',
            capture=lambda state: capture_state(state, archive=live, signal=np.zeros(3),
                done_ids={10}, cells=1, batches=1))
    state = tmp_path / 'pause' / 'state' / 'events.jsonl'
    state.write_bytes(state.read_bytes() + b'{}\n')
    with pytest.raises(ValueError, match='changed'):
        load(tmp_path / 'pause')


def test_the_request_file_survives_a_restart_and_is_cleared_by_a_checkpoint(tmp_path):
    controller = PauseController(tmp_path / 'pause')
    assert controller.check() is False
    PauseController(tmp_path / 'pause').request()
    # A fresh controller stands for the service after a restart: the request is a
    # file, so it is still there and still means the same thing.
    assert PauseController(tmp_path / 'pause').check() is True
    archive = _archive(tmp_path, 'events.jsonl', [{'10': []}])
    with EventArchive(tmp_path / 'live.jsonl', resume_from=archive) as live:
        PauseController(tmp_path / 'pause').save(phase='full_active',
            capture=lambda state: capture_state(state, archive=live, signal=np.zeros(3),
                done_ids={10}, cells=1, batches=1))
    assert PauseController(tmp_path / 'pause').check() is False
    clear(tmp_path / 'pause')
    assert load(tmp_path / 'pause') is None


def test_a_request_made_after_a_pass_started_is_still_observed(tmp_path):
    # A person pressing pause in the interface does so long after the pass began,
    # so the controller has to keep asking. One that latched its first answer
    # would run the whole twenty minutes and never see the request.
    controller = PauseController(tmp_path / 'pause')
    assert controller.check() is False
    controller.request()
    assert controller.check() is True
    # Once seen, the answer stays true even after the file is gone.
    controller.clear_request()
    assert controller.check() is True


def test_a_paused_pass_resumes_into_the_same_archive_and_signal(tmp_path, monkeypatch):
    batches = [[10, 20], [30, 40]]
    monkeypatch.setattr('service.application.feedback.population_bulk_replay.'
                        'PopulationWindowedFeedback', _Collector)
    monkeypatch.setattr('service.application.feedback.population_bulk_replay.'
                        'solve_population', _stub_solver(batches))
    continuous = replay_bulk_feedback_to_archive(**_arguments(),
        event_path=tmp_path / 'continuous.jsonl')
    # Stop at the first boundary: the checkpoint has to carry the archive, the
    # signal and the batch count, because those are what a resumed pass continues.
    armed = {'yes': True}
    controller = PauseController(tmp_path / 'pause', poll=lambda: armed['yes'])
    with pytest.raises(ReplayPaused):
        replay_bulk_feedback_to_archive(**_arguments(),
            event_path=tmp_path / 'paused.jsonl', pause=controller,
            pause_context={'phase': 'full_active', 'iteration': 1, 'history': [],
                           'previous': None, 'archives': {}, 'receipts': {}})
    resumed = load(tmp_path / 'pause')
    assert resumed['batches'] == 1 and resumed['done_ids'] == {10, 20}
    assert not (tmp_path / 'paused.jsonl').exists()
    armed['yes'] = False
    result = replay_bulk_feedback_to_archive(**_arguments(),
        event_path=tmp_path / 'resumed.jsonl', resume=resumed,
        resume_from=resumed['archive_path'])
    assert result['event_sha256'] == continuous['event_sha256']
    np.testing.assert_array_equal(result['neural_uv'], continuous['neural_uv'])


def test_a_pause_is_not_taken_while_a_batch_is_still_streaming(tmp_path, monkeypatch):
    # The solver marks a batch settled when its windows are in flight; the archive
    # and the signal only learn about a cell when its last window lands. A
    # checkpoint taken on the settled set published 23 186 done ids against 21 595
    # archived cells, and the resumed run then failed "Incomplete active source
    # population". Here the recording lags one batch behind, so no boundary is
    # honest and the pass must finish instead of checkpointing.
    class LaggingRecording(_Recording):
        streaming = set()

        def settled(self):
            # Settled covers what is in flight, exactly as the real recording
            # does; completed is what the archive and the signal have seen.
            return set(self.completed) | self.streaming

    class Lagging(_Collector):
        def __init__(self, expected_ids, *, resume=None, samples=4, **kwargs):
            super().__init__(expected_ids, resume=resume, samples=samples, **kwargs)
            self.recording = LaggingRecording(samples, resume)

        def factory(self, cells):
            # The previous batch lands now; this one only starts streaming.
            self.recording.completed.update(self.recording.streaming)
            self.recording.streaming = {int(body) for body in cells}
            self.recording.signal[0] += float(len(cells))
            return object()

        def finish(self):
            self.recording.completed.update(self.recording.streaming)
            self.recording.streaming = set()
            return self.recording.signal.copy()

    monkeypatch.setattr('service.application.feedback.population_bulk_replay.'
                        'PopulationWindowedFeedback', Lagging)
    monkeypatch.setattr('service.application.feedback.population_bulk_replay.'
                        'solve_population', _stub_solver([[10, 20], [30, 40]]))
    armed = {'yes': True}
    controller = PauseController(tmp_path / 'pause', poll=lambda: armed['yes'])
    result = replay_bulk_feedback_to_archive(**_arguments(),
        event_path=tmp_path / 'streaming.jsonl', pause=controller,
        pause_context={'phase': 'full_active', 'iteration': 1, 'history': [],
                       'previous': None, 'archives': {}, 'receipts': {}})
    assert result['cells'] == 4
    assert load(tmp_path / 'pause') is None


def test_a_resume_state_without_its_archive_is_rejected():
    with pytest.raises(ValueError, match='resume'):
        replay_bulk_feedback(**_arguments(), event_sink=lambda batch: None,
            resume={'batches': 1})