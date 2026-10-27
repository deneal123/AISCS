"""Only trusted run policy may exempt ordinary conversation from an appendix."""

import pytest

from service.application.reply_assembler import ReplyAssembler
from service.application.use_cases.agent_execution_use_cases import PostprocessAgentReplyUseCase
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.persona import use_persona
from service.domain.persona.registry import build_lens
from service.domain.pipeline import auto_mode
from service.domain.routing.auto.decision import AutoDecision

GREETING = "Привет! Рад продолжить нашу беседу. О чём хочешь поговорить сегодня? " * 5


def _reply(execution, metadata=None):
    assembler = ReplyAssembler(execution.usage)
    assembler.reply_parts.append(GREETING)
    return PostprocessAgentReplyUseCase().execute(
        reply_assembler=assembler, metadata=metadata or {}, execution=execution
    )[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_input",
    ["привет", "как дела чел", "привет бро", "ты Алина 28 лет", "не я Алина, а ты Алина"],
)
async def test_real_smalltalk_shortcut_suppresses_only_the_platform_appendix(user_input):
    with (
        use_run_execution(PrivateRunResources()) as execution,
        use_persona(build_lens(["psychologist"])),
    ):
        await auto_mode.resolve_auto_plan(user_input=user_input, execution=execution)
        assert execution.policy.flag("ordinary_conversation")
        assert _reply(execution) == GREETING
        assert execution.usage.receipts == ()


@pytest.mark.asyncio
async def test_continuation_keeps_the_specialized_warning():
    with (
        use_run_execution(PrivateRunResources()) as execution,
        use_persona(build_lens(["psychologist"])),
    ):
        await auto_mode.resolve_auto_plan(user_input="продолжай", execution=execution)
        assert not execution.policy.flag("ordinary_conversation")
        assert "не психотерапия" in _reply(execution)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision",
    [
        AutoDecision(route="general", source="llm", reason_code="shortcut_smalltalk"),
        AutoDecision(route="general", source="shortcut", reason_code="model_classification"),
        AutoDecision(route="deep_research", source="shortcut", reason_code="shortcut_smalltalk"),
    ],
)
async def test_untrusted_or_non_general_decisions_cannot_remove_warning(monkeypatch, decision):
    async def decide(*args, **kwargs):
        return decision

    monkeypatch.setattr(auto_mode, "decide_modes", decide)
    with use_run_execution(PrivateRunResources()) as execution:
        await auto_mode.resolve_auto_plan(user_input="обычная задача", execution=execution)
        assert not execution.policy.flag("ordinary_conversation")


@pytest.mark.asyncio
@pytest.mark.parametrize("bypass", [{"enabled": False}, {"route_override": "general"}])
async def test_bypassed_classifier_resets_previous_policy_signal(bypass):
    with use_run_execution(PrivateRunResources()) as execution:
        execution.policy.set_flag("ordinary_conversation", True)
        await auto_mode.resolve_auto_plan(user_input="привет", execution=execution, **bypass)
        assert not execution.policy.flag("ordinary_conversation")


def test_metadata_cannot_forge_a_greeting_exemption():
    with (
        use_run_execution(PrivateRunResources()) as execution,
        use_persona(build_lens(["psychologist"])),
    ):
        result = _reply(
            execution, {"auto": {"source": "shortcut", "reason_code": "shortcut_smalltalk"}}
        )
        assert "не психотерапия" in result


def test_greeting_exemption_does_not_strip_a_model_written_warning():
    from service.application.use_cases.agent_execution_use_cases import _ensure_disclaimers

    text = GREETING + " Это не психотерапия."
    assert _ensure_disclaimers(text, ordinary_conversation=True) == text
