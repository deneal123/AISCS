"""Discovery must preserve the same opaque ref returned by Docker create."""

import json

from drivers import docker_cli
from drivers.base import ContainerRef


async def test_discovery_uses_full_container_identity(monkeypatch):
    full_id = "a" * 64
    calls = []

    async def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "ps":
            return 0, (full_id if "--no-trunc" in args else full_id[:12]) + "\n", ""
        assert args[0] == "inspect"
        return 0, json.dumps([{"Config": {"Labels": {"gpthub.workspace": "1"}}}]), ""

    monkeypatch.setattr(docker_cli, "_docker", docker)
    found = await docker_cli.DockerCliDriver().list_managed()
    assert len(found) == 1
    assert found[0].ref == ContainerRef("docker", full_id)
    assert calls[1] == ("inspect", full_id)
