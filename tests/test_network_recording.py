import hashlib
import io
import json

import numpy as np
import pytest

from service.infrastructure.stimulation.network_recording import (
    acquire_independent_cells,
    record_independent_cells,
)
from service.infrastructure.stimulation.swc_reference import (
    record_swc_with_stimulus_artifact,
    simulate_swc_reference,
)

pytest.importorskip("neuron")


def pair(body_id, offset=0, **changes):
    swc = (f"1 1 0 {offset} 0 62.5 -1\n"
           f"2 3 12500 {offset} 0 62.5 1\n")
    config = dict(source_um=[0, 100, 0], return_um=[200, 100, 0], current_na=1000,
                  conductivity_s_m=.3, clearance_um=2)
    config.update(changes)
    solution = simulate_swc_reference(swc, **config)
    provenance = {"body_id": str(body_id), "morphology_sha256": "a" * 64, "components": 1,
                  "coordinate_frame": "MaleCNS native EM, micrometres", "configuration": config}
    return solution, provenance


def test_independent_currents_sum_but_common_stimulation_artifact_is_added_once():
    cells = [pair(1), pair(2, 1250)]
    e1, ref = [0, 200, 0], [200, 200, 0]
    for model in ("pointsource", "linesource"):
        channels = [record_swc_with_stimulus_artifact(*cell, e1, ref, source_model=model)
                    for cell in cells]
        combined = record_independent_cells(iter(cells), e1, ref, source_model=model)
        np.testing.assert_allclose(combined["neural_uv"], sum(c["neural_uv"] for c in channels))
        np.testing.assert_array_equal(
            combined["stimulus_artifact_uv"], channels[0]["stimulus_artifact_uv"]
        )
        np.testing.assert_allclose(
            combined["total_uv"], combined["neural_uv"] + combined["stimulus_artifact_uv"]
        )
        assert combined["cells"] == 2 and len(combined["ordered_sources_sha256"]) == 64


def test_swapping_recording_contacts_reverses_both_neural_and_stimulus_voltage():
    cells = [pair(1), pair(2, 1250)]
    e1, ref = [0, 200, 0], [200, 200, 0]
    for model in ('pointsource', 'linesource'):
        forward = record_independent_cells(cells, e1, ref, source_model=model)
        reversed_channel = record_independent_cells(cells, ref, e1, source_model=model)
        for name in ('neural_uv', 'stimulus_artifact_uv', 'total_uv'):
            np.testing.assert_allclose(reversed_channel[name], -forward[name],
                                       rtol=1e-12, atol=1e-12)
        np.testing.assert_array_equal(reversed_channel['stimulus_fraction'],
                                      forward['stimulus_fraction'])


def test_translating_cell_and_all_contacts_preserves_recorded_signal():
    original = pair(1)
    translated = pair(1, 1250, source_um=[0, 110, 0], return_um=[200, 110, 0])
    for model in ('pointsource', 'linesource'):
        first = record_independent_cells([original], [0, 200, 0], [200, 200, 0], source_model=model)
        second = record_independent_cells([translated], [0, 210, 0], [200, 210, 0],
                                          source_model=model)
        for name in ('neural_uv', 'stimulus_artifact_uv', 'total_uv'):
            np.testing.assert_allclose(second[name], first[name], rtol=1e-9, atol=1e-12)


def test_rejects_duplicate_sources_and_different_time_grids():
    first = pair(1)
    e1, ref = [0, 200, 0], [200, 200, 0]
    with pytest.raises(ValueError, match="duplicate"):
        record_independent_cells([first, first], e1, ref)
    with pytest.raises(ValueError, match="time grid"):
        record_independent_cells([first, pair(2, duration_ms=9)], e1, ref)
    with pytest.raises(ValueError, match="No cell"):
        record_independent_cells([], e1, ref)


def test_waveforms_must_match_even_when_zero_current_hides_artifact():
    first = pair(1, current_na=0)
    second_solution, second_provenance = pair(2, current_na=0)
    second_solution["stimulus_fraction"] = second_solution["stimulus_fraction"].copy()
    second_solution["stimulus_fraction"][0] = 0.5
    with pytest.raises(ValueError, match="waveform"):
        record_independent_cells([first, (second_solution, second_provenance)],
                                 [0, 200, 0], [200, 200, 0])


def test_acquisition_preserves_aggregate_provenance_and_blanking():
    combined = record_independent_cells([pair(1), pair(2, 1250)],
                                        [0, 200, 0], [200, 200, 0])
    acquired = acquire_independent_cells(combined, low_hz=100, high_hz=3000, recovery_ms=.5)
    assert acquired["recording_provenance"] == {
        "cells": 2, "ordered_sources_sha256": combined["ordered_sources_sha256"],
        "cell_provenance_sha256": combined["cell_provenance_sha256"],
        "cell_provenance_exported": False, "cell_provenance_fields_present": False,
        "source_model": "pointsource", "coupling": "independent cells",
        "stimulation_parameters": combined["stimulation_parameters"],
        "electrode_um": [0., 200., 0.], "reference_um": [200., 200., 0.],
        "coordinate_frame": "MaleCNS native EM, micrometres",
    }
    assert not acquired["valid_samples"].all()
    np.testing.assert_allclose(acquired["raw_total_uv"], combined["total_uv"])


def test_provenance_stream_has_checked_hash_and_full_records():
    first, second = pair(1), pair(2, 1250)
    sink = io.BytesIO()
    result = record_independent_cells([first, second], [0, 200, 0], [200, 200, 0],
                                      provenance_sink=sink)
    data = sink.getvalue()
    assert hashlib.sha256(data).hexdigest() == result["cell_provenance_sha256"]
    assert [json.loads(line) for line in data.splitlines()] == [first[1], second[1]]
    assert result["cell_provenance_exported"]
    assert not result["cell_provenance_fields_present"]


def test_incomplete_provenance_write_fails():
    class BrokenSink:
        def write(self, payload):
            return len(payload) - 1

    with pytest.raises(OSError, match="Incomplete"):
        record_independent_cells([pair(1)], [0, 200, 0], [200, 200, 0],
                                 provenance_sink=BrokenSink())
