"""NEURON integration checks; run in a fresh process without existing sections."""

import importlib
import os
import unittest

import numpy as np

try:
    import neuron  # noqa: F401
except ImportError:
    neuron = None


@unittest.skipIf(neuron is None, "NEURON is not installed")
class TestReferenceStimulation(unittest.TestCase):
    def test_stimulus_contact_cannot_cross_cable_between_midpoints(self):
        simulate = importlib.import_module(
            "service.infrastructure.stimulation.reference_cable"
        ).simulate_reference_cable
        with self.assertRaisesRegex(ValueError, "cable segment"):
            simulate([1, 0, 0], [150, 20, 0], 1, 0.3, clearance_um=0.1)

    def test_field_drives_membrane_and_moving_stim_changes_response(self):
        name = os.environ.get(
            "AISCS_STIM_REFERENCE_MODULE", "service.infrastructure.stimulation.reference_cable"
        )
        simulate = importlib.import_module(name).simulate_reference_cable
        options = {"source_um": [0, 20, 0], "return_um": [150, 20, 0],
                   "conductivity_s_m": 0.3, "clearance_um": 2}
        zero = simulate(current_na=0, **options)
        active = simulate(current_na=1000, **options)
        repeat = simulate(current_na=1000, **options)
        moved = simulate(current_na=1000, **{**options, "source_um": [-40, 20, 0]})
        np.testing.assert_array_equal(active["voltage_mv"], repeat["voltage_mv"])
        np.testing.assert_allclose(zero["field_mv"], 0)
        np.testing.assert_allclose(active["voltage_mv"][:, active["time_ms"] < 5],
                                   zero["voltage_mv"][:, zero["time_ms"] < 5], atol=1e-9)
        self.assertGreater(np.max(np.abs(active["voltage_mv"] - zero["voltage_mv"])), 0.01)
        self.assertGreater(np.max(np.abs(active["voltage_mv"] - moved["voltage_mv"])), 0.01)
        self.assertGreater(np.max(np.abs(active["extracellular_mv"])), 0.01)
        self.assertLess(np.max(np.abs(np.sum(active["membrane_current_na"], axis=0))), 1e-10)

    def test_refining_space_and_time_reduces_error_for_this_example(self):
        name = os.environ.get(
            "AISCS_STIM_REFERENCE_MODULE", "service.infrastructure.stimulation.reference_cable"
        )
        simulate = importlib.import_module(name).simulate_reference_cable
        options = {"source_um": [0, 20, 0], "return_um": [150, 20, 0],
                   "conductivity_s_m": 0.3, "clearance_um": 2, "current_na": 1000}
        for key, values in (("nseg", [25, 51, 101]), ("dt_ms", [0.05, 0.025, 0.0125])):
            results = [simulate(**options, **{key: value}) for value in values]
            reference = results[-1]
            trace = reference["voltage_mv"][len(reference["voltage_mv"]) // 2]
            errors = []
            for result in results[:-1]:
                candidate = result["voltage_mv"][len(result["voltage_mv"]) // 2]
                interpolated = np.interp(reference["time_ms"], result["time_ms"], candidate)
                errors.append(np.max(np.abs(trace - interpolated)))
            self.assertLess(errors[1], errors[0], key)


if __name__ == "__main__":
    unittest.main()
