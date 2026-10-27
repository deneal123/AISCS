import json
from types import SimpleNamespace

import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.video_summary import authoring
from service.domain.video_summary.evidence import (
    EvidenceChunk,
    EvidenceCue,
    NotesProtocolFailure,
    parse_grouped_draft,
)


def _chunk(text: str) -> EvidenceChunk:
    cues = tuple(EvidenceCue(f"cue_{index}", float(index * 10), text) for index in range(3))
    return EvidenceChunk(0, "source-digest", cues)


def _draft(chunk: EvidenceChunk, claims: tuple[str, ...]) -> dict:
    result = {}
    for (group, cues), claim in zip(chunk.coverage_groups().items(), claims, strict=True):
        cue = cues[0]
        result[group] = {
            "primary": {
                "title": f"Topic {group}",
                "points": [
                    {
                        "text": claim,
                        "evidence": [{"cue_ids": [cue.cue_id], "quote": cue.text}],
                    }
                ],
            }
        }
    return result


@pytest.mark.parametrize(
    ("source", "claim", "reason"),
    [
        (
            "The valve did not open after the alarm.",
            "The valve opened after the alarm.",
            "claim_polarity",
        ),
        (
            "Датчик не сработал до открытия клапана.",
            "Датчик сработал до открытия клапана.",
            "claim_polarity",
        ),
        (
            "If the pressure exceeds 5 bar, the valve closes.",
            "The valve closes.",
            "claim_condition",
        ),
        (
            "The delay lasted 12 seconds.",
            "The delay lasted 21 seconds.",
            "claim_quantity",
        ),
    ],
)
def test_claims_cannot_drop_quote_polarity_conditions_or_change_numbers(source, claim, reason):
    chunk = _chunk(source)
    claims = (claim, *(cue.text for cue in chunk.cues[1:]))

    with pytest.raises(NotesProtocolFailure) as failure:
        parse_grouped_draft(_draft(chunk, claims), chunk)

    assert failure.value.reason == reason


def test_claim_preserving_negative_condition_and_source_number_is_accepted():
    source = "If pressure does not exceed 5 bar, the valve does not open."
    chunk = _chunk(source)
    claims = tuple(cue.text for cue in chunk.cues)

    draft = parse_grouped_draft(_draft(chunk, claims), chunk)

    assert len(draft.sections) == 3


def test_valid_paraphrase_of_negative_source_is_not_rejected():
    chunk = _chunk("The valve did not open after the alarm.")
    claims = (
        "The valve remained closed after the alarm.",
        "The valve remained closed after the alarm.",
        "The valve remained closed after the alarm.",
    )

    draft = parse_grouped_draft(_draft(chunk, claims), chunk)

    assert len(draft.sections) == 3


def test_conditioned_claim_accepts_equivalent_when_formulation():
    chunk = _chunk("If the pressure exceeds 5 bar, the valve closes.")
    claims = (
        "When the pressure exceeds 5 bar, the valve closes.",
        "When the pressure exceeds 5 bar, the valve closes.",
        "When the pressure exceeds 5 bar, the valve closes.",
    )

    draft = parse_grouped_draft(_draft(chunk, claims), chunk)

    assert len(draft.sections) == 3


def test_unrelated_condition_does_not_poison_a_distinct_claim():
    chunk = _chunk("If pressure rises, the valve closes. The speaker summarizes the result.")
    claims = (
        "The speaker summarizes the result.",
        "The speaker summarizes the result.",
        "The speaker summarizes the result.",
    )

    draft = parse_grouped_draft(_draft(chunk, claims), chunk)

    assert len(draft.sections) == 3


def test_unrelated_claim_negation_does_not_mask_a_polarity_inversion():
    chunk = _chunk("The motor did not start; the warning light appeared.")
    claims = (
        "The motor started, but the warning light did not appear.",
        "The motor started, but the warning light did not appear.",
        "The motor started, but the warning light did not appear.",
    )

    with pytest.raises(NotesProtocolFailure) as failure:
        parse_grouped_draft(_draft(chunk, claims), chunk)

    assert failure.value.reason == "claim_polarity"


def test_unrelated_negation_in_neighbouring_sentence_does_not_poison_claim():
    cues = (
        EvidenceCue(
            "cue_0",
            0.0,
            "The speaker did not call it success. The process reached a stable state.",
        ),
        EvidenceCue("cue_1", 10.0, "The sensor remained closed throughout the test."),
        EvidenceCue("cue_2", 20.0, "The procedure ended after the final check."),
    )
    chunk = EvidenceChunk(0, "source-digest", cues)
    claims = (
        "The process reached a stable state.",
        "The sensor remained closed throughout the test.",
        "The procedure ended after the final check.",
    )

    draft = parse_grouped_draft(_draft(chunk, claims), chunk)

    assert len(draft.sections) == 3


@pytest.mark.asyncio
async def test_claim_alignment_failure_gets_one_same_model_repair(monkeypatch):
    chunk = _chunk("The valve opens after the signal.")
    attempts = 0

    async def model(**kwargs):
        nonlocal attempts
        attempts += 1
        response_text = "The valve does not open." if attempts == 1 else None
        groups = chunk.coverage_groups()
        arguments = {}
        properties = kwargs["tools"][0]["function"]["parameters"]["properties"]
        for group, cues in groups.items():
            cue = cues[0]
            claim = response_text if response_text is not None else cue.text
            arguments[group] = {
                "primary": {
                    "title": group,
                    "points": [
                        {
                            "text": claim,
                            "evidence": [{"cue_ids": [cue.cue_id], "quote": cue.text}],
                        }
                    ],
                }
            }
            assert group in properties
        response = SimpleNamespace(
            model="test-model",
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="submit_video_notes",
                                    arguments=json.dumps(arguments),
                                )
                            )
                        ],
                    ),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        execution.register_response_provider(response, "gigachat", "test-model")
        return response

    monkeypatch.setattr(authoring, "create_chat_completion", model)
    monkeypatch.setattr(authoring, "prompt_budget_per_run", lambda: 40_000)
    with use_run_execution(PrivateRunResources()) as execution:
        draft = await authoring.author_chunk(chunk, "Summarize", "test-model", execution)

        assert attempts == 2
        assert execution.usage.billable_calls == 2
        assert execution.policy.flags["video_protocol_repair_used"] is True
        assert all(
            point.text == chunk.cues[0].text
            for section in draft.sections
            for point in section.points
        )
