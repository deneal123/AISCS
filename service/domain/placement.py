import numpy as np

from service.contracts import SimulationConfig


def validate_contacts(config: SimulationConfig, starts, ends, diameters) -> None:
    """Reject contacts touching a compartment; do not silently clamp singular distances."""
    starts = np.asarray(starts, dtype=float)
    ends = np.asarray(ends, dtype=float)
    diameters = np.asarray(diameters, dtype=float)
    if (starts.ndim != 2 or starts.shape[1:] != (3,) or starts.shape != ends.shape
            or diameters.shape != (len(starts),) or not len(starts)
            or not np.isfinite(starts).all() or not np.isfinite(ends).all()
            or not np.isfinite(diameters).all() or np.any(diameters <= 0)):
        raise ValueError("Invalid neural source geometry")
    vectors = ends - starts
    length2 = np.sum(vectors * vectors, axis=1)
    if not np.isfinite(length2).all() or np.any(length2 <= 0):
        raise ValueError("Neural sources must have finite nonzero length")
    for name, contact in [("E1", config.placement.electrode), ("REF", config.placement.reference)]:
        point = np.asarray(contact.xyz())
        fraction = np.clip(np.sum((point - starts) * vectors, axis=1) / length2, 0, 1)
        distance = np.linalg.norm(point - (starts + fraction[:, None] * vectors), axis=1)
        if np.any(distance <= diameters / 2 + 2):
            raise ValueError(f"{name} must remain outside neural sources (2 um clearance)")
