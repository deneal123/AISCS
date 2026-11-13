"""Fail-closed checks for results of the experimental GPU solver."""


def require_valid_voltage_ranges(flags, cell_ids, *, allow_table_clamp=False):
    """Reject a batch if the CUDA rate table was used outside its domain.

    Call only after CUDA synchronization and copying flags to the host.
    Finite out-of-range voltages may be accepted only under the explicit
    experimental NEURON table-boundary policy; non-finite voltages always fail.
    """
    flags = list(flags)
    cell_ids = list(cell_ids)
    if not flags or len(flags) != len(cell_ids):
        raise ValueError('Range flags do not match the batch')
    if type(allow_table_clamp) is not bool or any(flag not in (0, 1, 2) for flag in flags):
        raise ValueError('Invalid voltage range flag')
    invalid = [str(cell_id) for flag, cell_id in zip(flags, cell_ids, strict=True)
               if flag == 2 or (flag == 1 and not allow_table_clamp)]
    if invalid:
        raise ValueError('Voltage outside rate-table range for cells: ' + ', '.join(invalid))
