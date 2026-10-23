"""Independent workspace processes cannot discover/reap each other's sandboxes."""

import json
from unittest.mock import AsyncMock

import pytest
from domain.policy import WorkspacePolicy

from drivers import docker_cli
from drivers.inventory import DockerInventory


@pytest.mark.parametrize("scope", ["1", "harness-20261021", "dev.b_2"])
def test_creation_uses_inventory_and_cannot_override_it(scope):
    argv = docker_cli._create_argv(
        "fixture",
        WorkspacePolicy(),
        {"gpthub.workspace": "other"},
        inventory=DockerInventory(scope),
    )
    assert [argv[i + 1] for i, arg in enumerate(argv) if arg == "--label"] == [
        f"gpthub.workspace={scope}"
    ]
    assert argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv


@pytest.mark.parametrize("scope", ["", "a=b", "*", " x", "x\n", "a" * 65])
def test_invalid_inventory_fails_closed_without_exposing_config(scope):
    with pytest.raises(ValueError, match="^invalid workspace Docker inventory scope$"):
        DockerInventory(scope)


def test_inventory_is_captured_at_process_construction(monkeypatch):
    monkeypatch.delenv("WORKSPACE_DOCKER_SCOPE", raising=False)
    default = docker_cli.DockerCliDriver()
    monkeypatch.setenv("WORKSPACE_DOCKER_SCOPE", "isolated")
    isolated = docker_cli.DockerCliDriver()
    monkeypatch.setenv("WORKSPACE_DOCKER_SCOPE", "changed")
    assert default.inventory.label == "gpthub.workspace=1"
    assert isolated.inventory.label == "gpthub.workspace=isolated"


async def test_discovery_filters_and_rechecks_exact_scope(monkeypatch):
    ids = ["a" * 64, "b" * 64]
    inventory = DockerInventory("harness-fixture")
    command = AsyncMock(
        side_effect=[
            (0, "\n".join(ids), ""),
            (0, json.dumps([{"Config": {"Labels": {"gpthub.workspace": inventory.scope}}}]), ""),
            (0, json.dumps([{"Config": {"Labels": {"gpthub.workspace": "1"}}}]), ""),
        ]
    )
    monkeypatch.setattr(docker_cli, "_docker", command)
    found = await docker_cli.DockerCliDriver(inventory=inventory).list_managed()
    assert [item.ref.container_id for item in found] == ids[:1]
    assert command.await_args_list[0].args == (
        "ps",
        "-aq",
        "--no-trunc",
        "--filter",
        "label=gpthub.workspace=harness-fixture",
    )
