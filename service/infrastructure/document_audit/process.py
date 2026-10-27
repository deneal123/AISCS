"""Local Linux process proof; age, lease expiry and other namespaces prove nothing."""

import hashlib
import json
import os
import socket
from pathlib import Path
from uuid import UUID


def _namespace() -> str | None:
    try:
        boot = str(UUID(Path("/proc/sys/kernel/random/boot_id").read_text().strip()))
        namespace = os.readlink("/proc/self/ns/pid")
        return hashlib.sha256(
            json.dumps([boot, namespace, socket.gethostname()]).encode()
        ).hexdigest()
    except (OSError, ValueError):
        return None


def _process(pid: int) -> tuple[str, int] | None:
    """None is authoritative absence only in the already matched namespace."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return None
    fields = raw.rsplit(")", 1)[1].split()
    return fields[0], int(fields[19])  # Linux stat fields 3 and 22, comm may contain spaces.


def process_owner() -> dict | None:
    try:
        namespace = _namespace()
        current = _process(os.getpid()) if namespace is not None else None
        if current is None:
            return None
        return {"namespace": namespace, "pid": os.getpid(), "start": current[1]}
    except (OSError, ValueError, IndexError):
        return None


def owner_stopped(owner: dict | None) -> bool:
    if owner is None or _namespace() != owner["namespace"]:
        return False
    try:
        current = _process(owner["pid"])
        return current is None or current[0] in {"Z", "X"} or current[1] != owner["start"]
    except (OSError, ValueError, IndexError):
        return False
