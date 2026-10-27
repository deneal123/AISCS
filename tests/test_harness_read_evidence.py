"""Усечённый исходник или дерево не подтверждают полное чтение критерия."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.harness.tools import _evidence
from service.domain.tools.ide import tools
from tests.test_ide_tools import REF, contents


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["file", "tree"])
@pytest.mark.parametrize("truncated", [False, True])
async def test_only_complete_observed_content_can_close_read_criterion(
    monkeypatch, surface, truncated
):
    path = "main.py" if surface == "file" else ""
    response = (
        contents(content="target\n" + "x" * (50000 if truncated else 5))
        if surface == "file"
        else {
            "entries": [],
            "truncated": truncated,
        }
    )

    async def call(*_args):
        return response

    monkeypatch.setattr(tools, "call", call)
    with use_run_execution(PrivateRunResources.from_request(workspace_ref=REF)) as execution:
        execution.task_state = SimpleNamespace(
            source_revision="r1",
            contract=SimpleNamespace(
                criteria=[SimpleNamespace(criterion_id="read", kind="read", target=path)]
            ),
        )
        handler = tools.ide_read if surface == "file" else tools.ide_tree
        outcome = await handler(None, json.dumps({"path": path}))
        assert outcome.succeeded
        proofs = _evidence(
            execution,
            SimpleNamespace(
                name="ide_read_file" if surface == "file" else "ide_list_files",
                arguments={"path": path},
            ),
            str(uuid4()),
            outcome,
        )
        assert bool(proofs) is not truncated
