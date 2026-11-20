"""Ordered host-side delivery of GPU windows, off the solve thread.

The recorded solver synchronises each window, copies the traces to the host and
then runs the whole recording chain - recorder accumulation, threshold crossings
and event selection - before the next window can launch. That chain measured
~5 s of a 28 s slice while the GPU itself was idle, so the launch was waiting on
Python.

This pipeline keeps the copies on the calling thread (they must follow the
synchronise) and runs everything after them on one ordered worker. Order matters
because every sink is positional: the recorder requires start == position and the
crossings need the previous sample. A single worker preserves that order while
letting the GPU run ahead by depth windows.

One pipeline serves a whole population pass, not one batch: closing it after
every batch drained the queue at the batch boundary, so the last windows of a
batch never overlapped anything and the worker sat idle between batches. The
sink therefore travels with each window instead of being fixed at construction.
"""

import queue
import threading

_STOP = object()


class WindowPipeline:
    """Deliver window payloads in submission order on a helper thread."""

    __slots__ = ("_queue", "_worker", "_error", "_closed")

    def __init__(self, *, depth=4, name="gpu-window-delivery"):
        if type(depth) is not int or depth < 1:
            raise ValueError("Invalid GPU window delivery depth")
        self._queue = queue.Queue(maxsize=depth)
        self._error = None
        self._closed = False
        self._worker = threading.Thread(target=self._run, name=name, daemon=True)
        self._worker.start()

    def _run(self):
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if self._error is not None:
                continue
            sink, start, end, payload = item
            try:
                rows = payload() if callable(payload) else payload
                sink(start, end, rows)
            except BaseException as exc:  # re-raised on the caller
                self._error = exc

    def submit(self, sink, start, end, payload):
        """Queue one window; raises a delivery failure from an earlier window.

        payload is either the rows or a zero-argument callable that builds them.
        Slicing the copied device traces into per-cell rows is pure numpy over
        host arrays, so it belongs on this worker and not in front of the next
        launch.
        """
        if self._closed:
            raise ValueError("GPU window pipeline is closed")
        if self._error is not None:
            raise self._error
        while True:
            try:
                self._queue.put((sink, start, end, payload), timeout=0.5)
                return
            except queue.Full:
                if self._error is not None:
                    raise self._error

    def close(self):
        """Drain the queue, join the worker and re-raise any delivery failure."""
        if self._closed:
            return
        self._closed = True
        while True:
            try:
                self._queue.put(_STOP, timeout=0.5)
                break
            except queue.Full:
                if self._error is not None:
                    break
        self._worker.join()
        if self._error is not None:
            raise self._error
