import numpy as np

from service.domain.visualization import compartment_events


def test_spatial_events_come_from_each_actual_compartment_voltage():
    time = np.array([0.0, 0.025, 0.05, 0.075])
    voltage = np.array([[-65.0, -5.0, 10.0, -65.0], [-65.0, -55.0, -5.0, -65.0]])
    assert compartment_events(time, voltage) == [
        {"segment_id": 0, "time_ms": 0.025},
        {"segment_id": 1, "time_ms": 0.05},
    ]
