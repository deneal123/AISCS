"""Deterministic Docker policy conformance; diagnostics never echo inspected values."""

from __future__ import annotations

import re
from decimal import Decimal

from domain.policy import WorkspacePolicy


def inspection_complete(info: object) -> bool:
    if not isinstance(info, dict):
        return False
    required = {
        "HostConfig": {
            "NetworkMode",
            "Privileged",
            "CapAdd",
            "CapDrop",
            "ReadonlyRootfs",
            "Memory",
            "MemorySwap",
            "PidsLimit",
            "NanoCpus",
            "SecurityOpt",
            "Tmpfs",
        },
        "Config": {"Image", "User", "WorkingDir"},
        "State": {"Running"},
        "NetworkSettings": {"Networks"},
    }
    complete = all(
        isinstance(info.get(key), dict) and fields <= info[key].keys()
        for key, fields in required.items()
    ) and isinstance(info.get("Mounts"), list)
    if not complete:
        return False
    host = info["HostConfig"]
    config = info["Config"]
    return (
        all(type(host[key]) is bool for key in ("Privileged", "ReadonlyRootfs"))
        and type(info["State"]["Running"]) is bool
        and all(
            host[key] is None or type(host[key]) is int
            for key in ("Memory", "MemorySwap", "PidsLimit", "NanoCpus")
        )
        and all(isinstance(config[key], str) for key in ("Image", "User", "WorkingDir"))
        and isinstance(host["NetworkMode"], str)
        and isinstance(info["NetworkSettings"]["Networks"], dict)
        and all(
            host[key] is None
            or isinstance(host[key], list)
            and all(isinstance(value, str) for value in host[key])
            for key in ("CapAdd", "CapDrop", "SecurityOpt")
        )
        and (host["Tmpfs"] is None or isinstance(host["Tmpfs"], dict))
        and all(
            isinstance(mount, dict)
            and isinstance(mount.get("Type"), str)
            and isinstance(mount.get("Destination"), str)
            for mount in info["Mounts"]
        )
    )


def _tmpfs_matches(value: object, quota: int) -> bool:
    if not isinstance(value, str):
        return False
    options: dict[str, str] = {}
    for part in value.split(","):
        key, _, argument = part.partition("=")
        if key in options or key not in {"rw", "exec", "size", "mode", "nosuid", "nodev"}:
            return False
        options[key] = argument
    if not {"rw", "exec", "size", "mode"} <= options.keys():
        return False
    size = re.fullmatch(r"(\d+)([kKmMgG]?)(?:[bB])?", options["size"])
    if size is None:
        return False
    factors = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
    try:
        return (
            int(size[1]) * factors[size[2].lower()] == quota
            and int(options["mode"], 8) == 0o1777
            and options["rw"] == options["exec"] == ""
        )
    except ValueError:
        return False


def isolation_complaints(info: dict, policy: WorkspacePolicy) -> list[str]:
    host = info.get("HostConfig") or {}
    config = info.get("Config") or {}
    network = info.get("NetworkSettings") or {}
    expected_tmpfs = {policy.root, "/tmp"}
    tmpfs = host.get("Tmpfs")
    mounts = info.get("Mounts")
    nano_cpus = int(Decimal(str(float(policy.cpus))) * 1_000_000_000)
    checks = {
        "network": host.get("NetworkMode") == policy.network,
        "privileged": host.get("Privileged") is False,
        "capabilities": not host.get("CapAdd") and host.get("CapDrop") == ["ALL"],
        "read_only_root": host.get("ReadonlyRootfs") is policy.read_only_root,
        "memory": host.get("Memory") == policy.memory_bytes,
        "memory_swap": host.get("MemorySwap") == policy.memory_bytes,
        "pids": host.get("PidsLimit") == policy.pids_limit,
        "cpu": host.get("NanoCpus") == nano_cpus,
        "privilege_escalation": host.get("SecurityOpt") == ["no-new-privileges"],
        "devices": not host.get("Devices") and not host.get("DeviceRequests"),
        "namespaces": all(
            host.get(key) in (None, "", "private") for key in ("PidMode", "IpcMode", "UTSMode")
        ),
        "volumes": not host.get("Binds") and not host.get("VolumesFrom"),
        "user": config.get("User") == policy.user,
        "image": config.get("Image") == policy.image,
        "working_directory": config.get("WorkingDir") == policy.root,
        "networks": isinstance(network.get("Networks"), dict)
        and set(network["Networks"]) == {policy.network},
        "running": (info.get("State") or {}).get("Running") is True,
        "tmpfs": isinstance(tmpfs, dict)
        and set(tmpfs) == expected_tmpfs
        and all(_tmpfs_matches(value, policy.quota_bytes) for value in tmpfs.values()),
        "mounts": isinstance(mounts, list)
        and all(
            isinstance(mount, dict)
            and mount.get("Type") == "tmpfs"
            and mount.get("Destination") in expected_tmpfs
            for mount in mounts
        ),
    }
    return [code for code, matched in checks.items() if not matched]
