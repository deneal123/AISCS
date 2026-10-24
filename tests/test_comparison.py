"""Регрессии приёмочного корпуса, не свидетельства качества реальных моделей."""

import json

import pytest

from local_llm.scripts.acceptance.candidates import CANDIDATES, artifact_for
from local_llm.scripts.acceptance.comparison import exercise, exercise_history, sampling_body


def completion(content="Готово", calls=None):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls" if calls else "stop",
                "message": {"role": "assistant", "content": content, "tool_calls": calls or []},
            }
        ],
        "usage": {"total_tokens": 10},
    }


CALL = {
    "id": "synthetic",
    "type": "function",
    "function": {"name": "read_receipt", "arguments": json.dumps({"step": 1})},
}


def correct(body):
    if body["messages"][-1]["role"] == "tool":
        assert body["tool_choice"] == "auto"
        return completion(body["messages"][-1]["content"])
    if "Прочитай" in body["messages"][-1]["content"]:
        return completion(None, [CALL])
    return completion()


def test_complete_corpus_and_voluntary_final():
    result = exercise(correct)
    assert result["passed"]
    assert len(result["cases"]) == 18
    assert sum(row["inferences"] for row in result["cases"]) == 27


@pytest.mark.parametrize(
    "behavior,failure",
    [
        (lambda body: completion(None, [CALL]), "repeated_tool"),
        (lambda body: completion("Выдуманный код"), "missing_grounded_answer"),
        (
            lambda body: {**completion(), "local_protocol_error": "tool_response_invalid"},
            "protocol_or_truncation",
        ),
    ],
)
def test_no_false_success(behavior, failure):
    result = exercise(behavior, repeats=1)
    assert not result["passed"]
    assert failure in {row["failure"] for row in result["cases"]}


def test_receipt_is_not_published_and_candidates_are_pinned():
    assert "rusmind" not in CANDIDATES
    for name, entry in CANDIDATES.items():
        artifact = artifact_for(name)
        assert len(entry.revision) == 40
        assert entry.revision in artifact.url
        assert len(artifact.sha256) == 64
        assert "/" not in artifact.filename
        assert artifact.size > 0
    assert all("text" not in row for row in exercise(correct, repeats=1)["cases"])


def test_candidate_entry_requires_explicit_opt_in(monkeypatch):
    from local_llm.scripts.acceptance import candidate_runtime

    monkeypatch.delenv("GPTHUB_MODEL_COMPARISON", raising=False)
    monkeypatch.setattr("sys.argv", ["comparison", "serve", "luma"])
    with pytest.raises(ValueError, match="comparison_dev_opt_in_required"):
        candidate_runtime.main()
    monkeypatch.setenv("GPTHUB_MODEL_COMPARISON", "dev-only")
    monkeypatch.setenv("GPTHUB_COMPARISON_PROJECT", "gpthub-prod")
    with pytest.raises(ValueError, match="comparison_project_invalid"):
        candidate_runtime.main()
    monkeypatch.setenv("GPTHUB_COMPARISON_PROJECT", "gpthub-dev")
    monkeypatch.setenv("GPTHUB_COMPARISON_CANDIDATE", "noir")
    with pytest.raises(ValueError, match="comparison_candidate_mismatch"):
        candidate_runtime.main()


def test_oversized_candidate_is_blocked_before_verification_or_bind(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    from local_llm.scripts.acceptance import candidate_runtime

    monkeypatch.setattr(
        candidate_runtime,
        "configuration",
        lambda env: SimpleNamespace(
            model_path=Path("/models/baseline.gguf"),
        ),
    )
    monkeypatch.setattr(
        candidate_runtime,
        "Path",
        lambda path: SimpleNamespace(
            exists=lambda: True,
            read_text=lambda: "1610612736",
        ),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Нельзя читать веса или открывать порт сверх memory policy")

    monkeypatch.setattr(candidate_runtime, "verified", forbidden)
    monkeypatch.setattr(candidate_runtime, "Gateway", forbidden)
    with pytest.raises(ValueError, match="comparison_memory_policy_blocked"):
        candidate_runtime.serve("t-lite")


def test_long_history_verifies_new_step_and_stops_after_wrong_final():
    import re

    def history_request(body):
        message = body["messages"][-1]
        if message["role"] == "tool":
            return completion(message["content"])
        step = int(re.search(r"\d+", message["content"])[0])
        return completion(
            None,
            [
                {
                    **CALL,
                    "function": {
                        "name": "read_receipt",
                        "arguments": json.dumps({"step": step}),
                    },
                }
            ],
        )

    result = exercise_history(history_request)
    assert result["passed"] and result["verified_rounds"] == 16
    assert result["inferences"] == 32

    def bad_final(body):
        return (
            completion("Старый результат")
            if body["messages"][-1]["role"] == "tool"
            else history_request(body)
        )

    result = exercise_history(bad_final)
    assert not result["passed"] and result["verified_rounds"] == 0
    assert result["inferences"] == 2 and result["failure"] == "history_final_invalid"


def test_sampling_profiles_do_not_change_source_request():
    body = {"temperature": 0, "seed": 0}
    assert sampling_body(body, "qwen3-nonthinking")["temperature"] == 0.7
    assert sampling_body(body, "qwen35-text")["temperature"] == 1
    assert body == {"temperature": 0, "seed": 0}
    with pytest.raises(ValueError, match="comparison_profile_invalid"):
        sampling_body(body, "unknown")


def test_qwen_nonthinking_uses_same_gateway_and_runtime(monkeypatch):
    from types import SimpleNamespace

    from local_llm.scripts.acceptance import candidate_runtime
    from local_llm.service.domain.model import MODEL_ID

    monkeypatch.setenv("LOCAL_LLM_API_KEY", "synthetic-comparison-key-" * 2)
    monkeypatch.setattr(
        candidate_runtime, "Path", lambda path: SimpleNamespace(exists=lambda: False)
    )
    monkeypatch.setattr(candidate_runtime, "verified", lambda *_: True)
    monkeypatch.setattr(candidate_runtime, "Gateway", lambda *args, **kwargs: "same-gateway")
    seen = []

    def capture(server, command, child):
        assert server == "same-gateway"
        seen.extend(command)
        return 7

    monkeypatch.setattr(candidate_runtime, "run", capture)
    assert candidate_runtime.serve("qwen3") == 7
    assert seen[seen.index("--alias") + 1] == MODEL_ID
    assert seen[seen.index("--model") + 1].endswith("Qwen3-0.6B-Q8_0.gguf")
    assert seen[seen.index("--reasoning") + 1] == "off"
    assert seen[seen.index("--top-k") + 1] == "20"
    assert seen[seen.index("--min-p") + 1] == "0"
    seen.clear()
    assert candidate_runtime.serve("granite1b") == 7
    assert seen[seen.index("--cache-ram") + 1] == "0"


def test_russian_review_checks_language_math_json_and_context():
    from local_llm.scripts.acceptance.language_review import review

    def answer(body):
        text = body["messages"][-1]["content"]
        if "17" in text:
            return completion("42")
        if "JSON" in text:
            return completion('{"ok":true,"count":3}')
        if "проект" in text:
            assert "Мурка" in body["messages"][1]["content"]
            return completion("Мурка")
        return completion("Здравствуйте!")

    assert review(answer)["passed"]
    assert not review(lambda body: completion("Hello!"))["passed"]


def test_boolean_step_is_not_accepted_as_integer_one():
    invalid = {**CALL, "function": {"name": "read_receipt", "arguments": '{"step":true}'}}
    result = exercise(lambda body: completion(None, [invalid]), repeats=1)
    assert not result["passed"]
    assert {row["failure"] for row in result["cases"] if row["case"].startswith("receipt")} == {
        "wrong_tool_arguments",
    }
