"""What an exported ECAP corpus promises, and what it refuses to promise."""

import json

import numpy as np

from service.infrastructure.body import ecap_export


def _record(index, *, ptp=12.5, fibres=7, escaped=True, samples=200, offset=0):
    signal = [0.0] * samples
    if ptp:
        signal[offset + 40] = -ptp / 2.0
        signal[offset + 60] = ptp / 2.0
    kept = list(signal[:samples - offset]) if offset else list(signal)
    return {
        "episode": f"ep{index:03d}",
        "site_um": (100.0 + index, 200.0, 300.0),
        "current_na": -3600.0 if escaped else 0.0,
        "duration_ms": samples // 20,
        "seed": index,
        "compound_action": {
            "format": "malecns-compound-action-potential-v1",
            "ptp_uv": ptp,
            "peak_at_ms": 3.0 if ptp else None,
            "recruited_fibres": fibres,
            "classes": {"ascending_small": fibres},
            "skipped_spikes": 0,
            "samples": len(kept),
            "waveform_uv": kept,
            "recruitment_curve": [(n, 0.5 * n) for n in range(1, fibres + 1)],
        },
        "body": {"escape_latency_ms": 9.5 if escaped else None,
                 "curl_change_rad": 0.25 if escaped else 0.0,
                 "displacement_mm": 1.5 if escaped else 0.0},
    }


def test_export_writes_the_five_files_and_a_card(tmp_path=None):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        card = ecap_export.export([_record(0), _record(1)], directory)
        for name in card["files"]:
            assert (Path(directory) / name).exists(), name
        assert card["format"] == "malecns-ecap-compatible-v1"
        assert card["episodes"] == 2
        assert card["episodes_without_channel"] == 0
        assert card["calibrated"] is False
        assert card["paired_with_behaviour"] is True
        assert "recruited_fibres" in card["exact_columns"]
        assert "ptp_uv" in card["modelled_columns"]


def test_the_waveform_matrix_is_square_and_shares_one_timebase():
    bundle = ecap_export.waveforms([_record(0), _record(1, samples=150)])
    assert bundle["signals"].shape == (2, 200)
    assert len(bundle["time_ms"]) == 200
    # The short channel is padded with zeros at the end, not resampled:
    # inventing samples would be a measurement the episode never made.
    assert np.all(bundle["signals"][1, 150:] == 0.0)
    assert abs(bundle["time_ms"][1] - 0.05) < 1e-9


def test_a_channel_that_is_absent_is_dropped_and_counted_not_zero_filled():
    silent = _record(1)
    silent["compound_action"] = {}
    bundle = ecap_export.waveforms([_record(0), silent])
    assert bundle["signals"].shape[0] == 1
    assert len(bundle["records"]) == 1
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        card = ecap_export.export([_record(0), silent], directory)
        assert card["episodes"] == 1
        assert card["episodes_without_channel"] == 1


def test_the_landmarks_are_the_first_trough_and_the_peak_after_it():
    signal = np.zeros(100)
    signal[10] = -4.0
    signal[30] = 6.0
    time = np.arange(100) * 0.05
    marks = ecap_export.n1_p1(signal, time)
    assert abs(marks["n1_uv"] + 4.0) < 1e-9
    assert abs(marks["p1_uv"] - 6.0) < 1e-9
    assert abs(marks["n1_ms"] - 0.5) < 1e-9
    assert abs(marks["p1_ms"] - 1.5) < 1e-9


def test_a_flat_channel_reports_no_landmarks_rather_than_zero_volts():
    marks = ecap_export.n1_p1(np.zeros(50), np.arange(50) * 0.05)
    assert marks["n1_uv"] is None and marks["p1_uv"] is None


def test_a_peak_before_the_search_window_is_ignored():
    signal = np.zeros(100)
    signal[2] = -9.0
    signal[50] = -2.0
    signal[70] = 3.0
    marks = ecap_export.n1_p1(signal, np.arange(100) * 0.05, search_ms=(1.0, 40.0))
    assert abs(marks["n1_uv"] + 2.0) < 1e-9


def test_the_recruitment_table_is_sorted_by_fibres_and_keeps_every_episode():
    rows = ecap_export.recruitment_csv([("e1", [(3, 1.5), (1, 0.5), (2, 1.0)]),
                                        ("e2", [(1, 0.4)])])
    assert [r["recruited_fibres"] for r in rows] == [1, 2, 3, 1]
    assert rows[0]["episode"] == "e1" and rows[3]["episode"] == "e2"


def test_every_row_carries_the_behaviour_of_its_own_episode():
    import csv
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        ecap_export.export([_record(0, escaped=True), _record(1, escaped=False)],
                           directory)
        with open(Path(directory) / "channels.csv", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 2
        assert rows[0]["escaped"] == "True"
        assert rows[1]["escaped"] == "False"
        assert float(rows[0]["recruited_fibres"]) == 7.0
        assert rows[1]["escape_latency_ms"] == ""
        assert rows[0]["calibrated"] == "False"


def test_an_export_without_any_channel_still_writes_a_readable_card():
    import tempfile

    silent = _record(0)
    silent["compound_action"] = {}
    with tempfile.TemporaryDirectory() as directory:
        card = ecap_export.export([silent], directory)
        assert card["episodes"] == 0
        assert card["ptp_range_uv"] is None
        assert card["waveform_samples"] == 0
        json.dumps(card)
