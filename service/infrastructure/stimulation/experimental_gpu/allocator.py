"""Bound the host allocator's retained arena for the population prepare path.

The prepare path allocates a fresh set of per-cell arrays for every batch and
lets them go again. glibc keeps the freed pages in per-thread arenas, so the
resident set of the process climbs batch after batch even though the live
object graph stays constant (measured: 283 919 -> 283 927 Python objects while
RSS went 0.98 -> 3.70 GB over one 166 700-cell walk).

Two knobs fix it, both measured on the full population walk:

* M_ARENA_MAX=2, M_MMAP_THRESHOLD=M_TRIM_THRESHOLD=128 KiB cap how much the
  allocator holds back: peak RSS 1.95 GB, final 0.45 GB, against 3.70 GB.
* an explicit malloc_trim(0) between batches returns what is still cached.

mallopt has to run after the interpreter started, so this module exposes it as
a call instead of relying on the MALLOC_* environment variables.
"""

from __future__ import annotations

import ctypes
import gc
import os

_M_ARENA_MAX = -8
_M_MMAP_THRESHOLD = -3
_M_TRIM_THRESHOLD = -1
_THRESHOLD_BYTES = 131072

_libc = None
_tuned = False


def _library():
    global _libc
    if _libc is None:
        try:
            _libc = ctypes.CDLL('libc.so.6')
        except OSError:
            _libc = False
    return _libc or None


def enabled() -> bool:
    return os.environ.get('GENERATOR_ALLOCATOR_TUNING', '1') not in ('0', '', 'false')


def tune() -> bool:
    """Cap glibc's retained arena. Returns True when the tuning was applied."""
    global _tuned
    if _tuned or not enabled():
        return _tuned
    library = _library()
    if library is None:
        return False
    try:
        applied = (library.mallopt(_M_ARENA_MAX, 2)
                   and library.mallopt(_M_MMAP_THRESHOLD, _THRESHOLD_BYTES)
                   and library.mallopt(_M_TRIM_THRESHOLD, _THRESHOLD_BYTES))
    except Exception:
        return False
    _tuned = bool(applied)
    return _tuned


def release() -> None:
    """Return the freed pages of the retained arena to the operating system."""
    if not _tuned:
        return
    library = _library()
    if library is None:
        return
    gc.collect()
    try:
        library.malloc_trim(0)
    except Exception:
        pass
