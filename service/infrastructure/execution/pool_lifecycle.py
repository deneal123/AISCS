"""Ensure Linux pool workers terminate if their owning executor disappears."""

from __future__ import annotations

import os
import signal
import sys


def guard_pool_owner(expected_parent_pid: int) -> None:
    """Arm Linux parent-death signalling and close the startup race.

    Run only as a process-pool initializer. Other platforms retain their
    existing process-management behavior; this helper makes no guarantee for
    them. It does not replace explicit cancellation of an owned process group.
    """
    if type(expected_parent_pid) is not int or expected_parent_pid < 1:
        raise ValueError('Invalid pool owner PID')
    if not sys.platform.startswith('linux'):
        return

    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                      ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    if prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    # The owner could have died before prctl was installed. In that case no
    # death signal will arrive; fail closed before accepting any workload.
    if os.getppid() != expected_parent_pid:
        raise RuntimeError('Pool owner disappeared before worker initialization')
