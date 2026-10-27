"""Потерянный вывод нельзя исправить автоматическим повтором уже выполненного кода."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.domain.ide.commands import CommandSpec
from service.services.chat.persistence.harness.commands import recipes
from service.shared.harness_protocol import HarnessFailure
from tests.test_task_contract import state


@pytest.mark.asyncio
@pytest.mark.parametrize("shell", [False, True])
async def test_unrecoverable_previous_output_blocks_even_a_new_shell_recipe(shell):
    async def scalar(statement, _params):
        if "EXISTS" in str(statement):
            return True
        return {"verification": {"status": "blocked", "reason": "output_unavailable"}}

    db = SimpleNamespace(scalar=AsyncMock(side_effect=scalar), execute=AsyncMock())
    spec = (
        CommandSpec(profile="shell", command="python3 a.py")
        if shell
        else CommandSpec(
            profile="python_script",
            target="src/hello_world.py",
            expected_stdout="hello",
            criterion_id="test",
        )
    )
    with pytest.raises(HarnessFailure, match="verification_unavailable"):
        await recipes.bind_recipe(
            db, {"task_id": uuid4()}, SimpleNamespace(state=state(), continuation=None), spec
        )
    db.execute.assert_not_awaited()
