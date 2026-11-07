"""Resource limits for explicit, non-truncated target recordings."""

MAX_TARGET_RESPONSE_VALUES = 4_000_000


def can_capture_targets(count: int, duration_ms: int) -> bool:
    return (type(count) is int and type(duration_ms) is int
            and count > 0 and duration_ms >= 1
            and count * (duration_ms + 1) <= MAX_TARGET_RESPONSE_VALUES)


def network_sample_ticks(count: int, duration_ms: int) -> list[int] | None:
    """Bound whole-network snapshots while keeping both endpoints and recording their times."""
    if type(count) is not int or type(duration_ms) is not int or count <= 0 or duration_ms < 1:
        return None
    slots = MAX_TARGET_RESPONSE_VALUES // count
    if slots < 2:
        return None
    stride = max(1, (duration_ms + slots - 2) // (slots - 1))
    ticks = list(range(0, duration_ms, stride)) + [duration_ms]
    return ticks if len(ticks) * count <= MAX_TARGET_RESPONSE_VALUES else None
