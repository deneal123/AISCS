"""Signal only the exact trusted supervisor, never a project-provided PGID."""

import os
import signal
import sys

pid, expected = int(sys.argv[1]), sys.argv[2]
if pid <= 1:
    raise SystemExit(2)
try:
    descriptor = os.pidfd_open(pid)
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as source:
            actual = source.read().rsplit(")", 1)[1].split()[19]
        if actual != expected:
            raise SystemExit(3)
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
    finally:
        os.close(descriptor)
except ProcessLookupError:
    pass
except FileNotFoundError:
    pass
