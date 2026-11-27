from __future__ import annotations

import numpy as np

from service.infrastructure.body.episode import Episode
from service.infrastructure.body.dataset import (
    compound_action_labels, compound_action_summary, label, summarize)

RECEIPT = {
    "format": "malecns-compound-action-potential-v1",
    "volleys": 40, "recruited_fibres": 40, "classes": {"ascending_small": 38,
    "ascending_large": 2}, "ptp_uv": 12.5, "peak_abs_uv": 7.0,
    "sampling_hz": 20000.0, "crossing_ms": 1.0, "triphasic": True,
    "calibrated": False, "calibration_note": "model", "diameters": "class",
    "skipped_spikes": 3, "peak_at_ms": 4.25, "preparation": "whole_graph_forced",
    "fibre_classes": True,
}


def _episode():
    episode = Episode(seed=1, site_um=(0.0, 0.0, 0.0), current_na=-3600.0,
                      source_cells=[1, 2], duration_ms=10, reason="test")
    ids = np.asarray([1, 2, 3])
    episode.record_network(spikes=np.asarray([1]),
                          spike_neurons=np.asarray([3]),
                          spike_times_ms=np.asarray([2.0]),
                          activity=np.asarray([0, 1, 0]), cell_ids=ids)
    episode.record_body(start=(0., 0., 0.), end=(0.001, 0., 0.), curl_start=0.,
                        curl_end=-0.2, escape_latency_ms=9.0, peak_height_cm=0.05,
                        min_height_cm=0.04, motor_spikes=4)
    return episode


def test_an_episode_records_the_channel_and_keeps_it_out_of_the_field_block():
    episode = _episode()
    episode.record_compound_action(RECEIPT)
    record = episode.record()
    assert record["compound_action"]["recruited_fibres"] == 40
    # The field block is a measurement the twin does not own, so the model output
    # must not leak into it.
    assert record["electrode"] == {}


def test_a_malformed_receipt_is_rejected():
    for bad in ({}, {"format": "something-else"}, None, "text"):
        try:
            _episode().record_compound_action(bad)
        except ValueError:
            continue
        raise AssertionError("bad receipt was accepted")


def test_the_dataset_row_carries_the_exact_fibre_count():
    episode = _episode()
    episode.record_compound_action(RECEIPT)
    row = label(episode.record())
    block = row["compound_action"]
    assert block["present"] is True
    assert block["recruited_fibres"] == 40
    assert block["classes"] == {"ascending_small": 38, "ascending_large": 2}
    assert block["calibrated"] is False
    assert block["peak_at_ms"] == 4.25


def test_an_episode_without_a_channel_says_so_instead_of_reporting_zero():
    block = label(_episode().record())["compound_action"]
    assert block["present"] is False
    assert block["recruited_fibres"] == 0
    assert block["calibrated"] is False


def test_the_summary_separates_absent_channels_from_empty_ones():
    with_channel = _episode()
    with_channel.record_compound_action(RECEIPT)
    records = [with_channel.record(), _episode().record()]
    summary = compound_action_summary(records)
    assert summary["episodes"] == 2
    assert summary["channels"] == 1
    assert summary["absent"] == 1
    assert summary["classes"] == {"ascending_small": 38, "ascending_large": 2}
    assert summary["recruited_range"] == [40, 40]
    assert summary["calibrated"] is False


def test_the_body_summary_is_unchanged_by_a_channel():
    plain = _episode().record()
    with_channel = _episode()
    with_channel.record_compound_action(RECEIPT)
    assert summarize([plain])["counts"] == summarize([with_channel.record()])["counts"]
