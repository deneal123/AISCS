"""Resource and privilege claims must match actual Docker inspection, not just exist."""

import copy

import pytest
from domain.policy import WorkspacePolicy

from drivers.docker_cli import _isolation_complaints
from drivers.isolation import inspection_complete


def inspection(policy=None):
    policy = policy or WorkspacePolicy()
    options = f"rw,exec,size={policy.quota_bytes},mode=1777"
    return {
        "HostConfig": {
            "NetworkMode": policy.network,
            "Privileged": False,
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "ReadonlyRootfs": policy.read_only_root,
            "Memory": policy.memory_bytes,
            "MemorySwap": policy.memory_bytes,
            "PidsLimit": policy.pids_limit,
            "NanoCpus": int(policy.cpus * 1_000_000_000),
            "SecurityOpt": ["no-new-privileges"],
            "Tmpfs": {policy.root: options, "/tmp": options},
        },
        "Config": {"Image": policy.image, "User": policy.user, "WorkingDir": policy.root},
        "NetworkSettings": {"Networks": {policy.network: {}}},
        "State": {"Running": True},
        "Mounts": [],
    }


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("HostConfig", "Memory", 1024 * 1024 * 1024),
        ("HostConfig", "MemorySwap", -1),
        ("HostConfig", "PidsLimit", 4096),
        ("HostConfig", "NanoCpus", 0),
        ("HostConfig", "CapDrop", None),
        ("HostConfig", "SecurityOpt", []),
        ("HostConfig", "SecurityOpt", ["no-new-privileges", "seccomp=unconfined"]),
        ("HostConfig", "SecurityOpt", ["no-new-privileges", "apparmor=unconfined"]),
        ("HostConfig", "Devices", [{"PathOnHost": "private-device-marker"}]),
        ("HostConfig", "DeviceRequests", [{"Capabilities": [["gpu"]]}]),
        ("HostConfig", "PidMode", "host"),
        ("HostConfig", "IpcMode", "host"),
        ("HostConfig", "Binds", ["private-bind-marker:/workspace"]),
        ("HostConfig", "VolumesFrom", ["private-container-marker"]),
        ("Config", "User", "0:0"),
        ("Config", "Image", "private-image-marker"),
        ("Config", "WorkingDir", "/"),
        ("NetworkSettings", "Networks", {"none": {}, "private-network-marker": {}}),
        ("State", "Running", False),
    ],
)
def test_weakened_or_different_policy_is_rejected_without_private_detail(section, key, value):
    data = inspection()
    data[section][key] = value
    complaints = _isolation_complaints(data, WorkspacePolicy())
    assert complaints
    assert "private-" not in repr(complaints)


@pytest.mark.parametrize("change", ["oversize", "missing", "readonly", "bind", "extra"])
def test_workspace_storage_cannot_escape_approved_tmpfs(change):
    data = inspection()
    if change == "oversize":
        data["HostConfig"]["Tmpfs"]["/workspace"] = "rw,exec,size=1073741824,mode=1777"
    elif change == "missing":
        data["HostConfig"]["Tmpfs"].pop("/workspace")
    elif change == "readonly":
        data["HostConfig"]["Tmpfs"]["/workspace"] = "ro,size=268435456,mode=1777"
    elif change == "bind":
        data["Mounts"] = [{"Type": "bind", "Source": "private-host-marker"}]
    else:
        data["HostConfig"]["Tmpfs"]["/host"] = "rw,exec,size=268435456,mode=1777"
    assert _isolation_complaints(data, WorkspacePolicy())


@pytest.mark.parametrize("custom", [False, True])
def test_full_matching_policy_is_admitted(custom):
    policy = (
        WorkspacePolicy(memory_bytes=268435456, pids_limit=128, cpus=0.5, root="/project")
        if custom
        else WorkspacePolicy()
    )
    assert _isolation_complaints(inspection(policy), policy) == []


def test_inspection_is_not_mutated():
    data = inspection()
    original = copy.deepcopy(data)
    _isolation_complaints(data, WorkspacePolicy())
    assert data == original


@pytest.mark.parametrize(
    "corruption", ["missing", "bool_limit", "string_bool", "bad_caps", "bad_mount"]
)
def test_unusable_inspection_is_not_valid_evidence(corruption):
    data = inspection()
    assert inspection_complete(data)
    if corruption == "missing":
        del data["Config"]["User"]
    elif corruption == "bool_limit":
        data["HostConfig"]["PidsLimit"] = True
    elif corruption == "string_bool":
        data["HostConfig"]["Privileged"] = "false"
    elif corruption == "bad_caps":
        data["HostConfig"]["CapDrop"] = "ALL"
    else:
        data["Mounts"] = ["private-malformed-mount-marker"]
    assert not inspection_complete(data)
