"""Bounded window execution for the experimental GPU solver."""

from .validation import require_valid_voltage_ranges


def execute_windows(*, total_steps, window_steps, launch, synchronize, read_flags,
                    cell_ids, progress=None, check_cancelled=None, allow_table_clamp=False):
    """Run ordered windows and fail before publishing an invalid result.

    ``launch(start, end)`` owns device buffers; indices define the same
    start-exclusive/end-inclusive windows as the Hines kernel. Synchronization
    precedes inspection of flags, progress and the next launch. Cancellation
    and errors propagate to the caller. This is not the service executor.
    """
    if (type(total_steps) is not int or total_steps < 1
            or type(window_steps) is not int or window_steps < 1
            or not callable(launch) or not callable(synchronize) or not callable(read_flags)
            or not isinstance(cell_ids, (list, tuple)) or not cell_ids
            or (progress is not None and not callable(progress))
            or (check_cancelled is not None and not callable(check_cancelled))):
        raise ValueError('Invalid GPU window execution settings')
    for start in range(0, total_steps, window_steps):
        if check_cancelled is not None:
            check_cancelled()
        end = min(start + window_steps, total_steps)
        launch(start, end)
        synchronize()
        require_valid_voltage_ranges(read_flags(), cell_ids, allow_table_clamp=allow_table_clamp)
        if progress is not None:
            progress(end, total_steps)
