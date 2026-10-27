import numpy as np

from service.contracts import SimulationConfig


def validate_contacts(config: SimulationConfig, starts, ends, diameters) -> None:
    """Reject contacts touching a compartment; do not silently clamp singular distances."""
    vectors = ends - starts
    length2 = np.sum(vectors * vectors, axis=1)
    for name, contact in [("E1", config.placement.electrode), ("REF", config.placement.reference)]:
        point = np.asarray(contact.xyz())
        fraction = np.clip(np.sum((point - starts) * vectors, axis=1) / length2, 0, 1)
        distance = np.linalg.norm(point - (starts + fraction[:, None] * vectors), axis=1)
        if np.any(distance <= diameters / 2 + 2):
            raise ValueError(f"{name} must remain outside neural sources (2 um clearance)")
