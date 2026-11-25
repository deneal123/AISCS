"""The episode record: what it may claim, what it must refuse to claim.

The dataset rests on these records, so the rules are tested rather than described:
a record never labels a cell, never labels a feeling, and refuses a raster whose
three columns disagree.
"""

import numpy as np
import pytest

from service.infrastructure.body.episode import (FORMAT, LABEL_ESCAPE,
                                                 LABEL_NO_ESCAPE,
                                                 LABEL_NOXIOUS_INPUT, Episode)


def _episode(**overrides):
    arguments = dict(seed=1, site_um=(470.0, 390.0, 950.0), current_na=-3600.0,
                     source_cells=[20, 10], duration_ms=4, reason="test")
    arguments.update(overrides)
    return Episode(**arguments)


def test_a_record_keeps_the_raster_as_body_ids_and_the_activity_per_tick():
    episode = _episode()
    network = episode.record_network(spikes=[0, 1, 2], spike_neurons=[7, 9, 7],
                                     spike_times_ms=[2.0, 1.0, 1.0],
                                     activity=[0, 2, 1, 0, 0], cell_ids=range(3))
    assert network["spike_count"] == 3
    assert network["cell_count"] == 2
    assert network["active_ticks"] == 2
    assert network["first_active_tick"] == 1
    assert network["last_active_tick"] == 2
    assert network["peak_activity"] == 2
    # Sorted by time and stable within a tick.
    assert network["raster"] == [[9, 1], [7, 1], [7, 2]]


def test_an_empty_activity_vector_reports_no_active_tick():
    episode = _episode()
    network = episode.record_network(spikes=[], spike_neurons=[], spike_times_ms=[],
                                     activity=[0, 0, 0, 0, 0], cell_ids=range(3))
    assert network["active_ticks"] == 0
    assert network["first_active_tick"] is None
    assert network["last_active_tick"] is None
    assert network["peak_activity"] == 0


def test_a_raster_whose_columns_disagree_is_refused():
    episode = _episode()
    with pytest.raises(ValueError):
        episode.record_network(spikes=[1, 2], spike_neurons=[1], spike_times_ms=[1, 2],
                               activity=[1], cell_ids=range(2))
    with pytest.raises(ValueError):
        episode.record_network(spikes=[1], spike_neurons=[1], spike_times_ms=[1],
                               activity=np.zeros((2, 2)), cell_ids=range(2))
    with pytest.raises(ValueError):
        episode.record_network(spikes=[1], spike_neurons=[1], spike_times_ms=[1],
                               activity=[-1], cell_ids=range(2))


def test_the_body_block_reports_millimetres_and_the_escape_latency():
    episode = _episode()
    body = episode.record_body(start=(0.0, 0.0, 0.0), end=(0.1, 0.05, -0.01),
                               curl_start=0.0, curl_end=-0.3, escape_latency_ms=9.5,
                               peak_height_cm=0.02, min_height_cm=-0.01)
    assert body["displacement_x_mm"] == pytest.approx(1.0)
    # Rounding is part of the record: millimetres to four decimals.
    assert body["displacement_mm"] == pytest.approx(round(float(np.hypot(1.0, 0.5)), 4), rel=1e-4)
    assert body["curl_change_rad"] == pytest.approx(-0.3)
    assert body["escape_latency_ms"] == 9.5


def test_labels_say_what_happened_and_never_name_a_cell():
    episode = _episode()
    episode.record_network(spikes=[0], spike_neurons=[5], spike_times_ms=[1.0],
                           activity=[0, 1], cell_ids=range(6))
    episode.record_body(start=(0, 0, 0), end=(0, 0, 0), curl_start=0.0, curl_end=0.0,
                        escape_latency_ms=None, peak_height_cm=0.0, min_height_cm=0.0)
    record = episode.record()
    assert record["format"] == FORMAT
    assert record["source_cells"] == [10, 20]
    assert record["source_cell_count"] == 2
    assert record["labels"] == [LABEL_NOXIOUS_INPUT, LABEL_NO_ESCAPE]
    assert record["label_scope"] == "the applied input, not a cell and not a feeling"
    # No field anywhere is called a pain or a nociceptor.
    text = str(record).lower()
    for forbidden in ("pain", "noxious_cell", "is_nociceptor", "feeling"):
        assert forbidden not in text.replace(record["label_scope"], "")


def test_an_escape_flips_the_label_without_touching_the_others():
    episode = _episode()
    episode.record_network(spikes=[0], spike_neurons=[5], spike_times_ms=[1.0],
                           activity=[0, 1], cell_ids=range(6))
    episode.record_body(start=(0, 0, 0), end=(0.2, 0, 0), curl_start=0.0, curl_end=-0.4,
                        escape_latency_ms=12.0, peak_height_cm=0.03, min_height_cm=0.0)
    assert episode.labels() == [LABEL_NOXIOUS_INPUT, LABEL_ESCAPE]


def test_a_silent_episode_carries_no_noxious_label():
    episode = _episode()
    episode.record_network(spikes=[], spike_neurons=[], spike_times_ms=[],
                           activity=np.zeros(5, dtype=np.int64), cell_ids=range(6))
    episode.record_body(start=(0, 0, 0), end=(0, 0, 0), curl_start=0.0, curl_end=0.0,
                        escape_latency_ms=None, peak_height_cm=0.0, min_height_cm=0.0)
    assert episode.labels() == [LABEL_NO_ESCAPE]
