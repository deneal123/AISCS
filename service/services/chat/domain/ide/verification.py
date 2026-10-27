"""Deterministic recipe checks over receipts, independent of orchestration."""

import hashlib
import json


def recipe(spec):
    return {key: getattr(spec, key) for key in ("profile", "target", "expected_stdout")}


def execution_request(spec):
    return {
        "argv": ["/bin/sh", "-c", spec.command]
        if spec.profile == "shell"
        else ["python3", spec.target],
        "verification_profile": spec.profile if spec.profile in {"unittest", "pytest"} else None,
        "verification_target": spec.target,
    }


def verify(spec, result, metrics):
    digest = hashlib.sha256(json.dumps(recipe(spec), sort_keys=True).encode()).hexdigest()

    def outcome(status, reason=""):
        return {"status": status, "reason": reason, "recipe_digest": digest}

    if spec.profile == "shell":
        return outcome("not_requested")
    if result is None or result.truncated:
        return outcome("blocked", "output_unavailable")
    if result.exit_code == 127:
        return outcome("blocked", "runtime_unavailable")
    if result.timed_out:
        return outcome("failed", "command_timeout")
    # pytest возвращает 5 при отсутствии собранных тестов. Причину подтверждает
    # только отдельный отчёт доверенного исполнителя, не текст stdout/stderr.
    no_pytest_tests = spec.profile == "pytest" and result.exit_code == 5
    if result.exit_code != 0 and not no_pytest_tests:
        return outcome("failed", "verification_failed")
    if spec.profile in {"unittest", "pytest"}:
        if (
            not isinstance(metrics, dict)
            or type(metrics.get("version")) is not int
            or metrics.get("version") != 1
            or metrics.get("profile") != spec.profile
            or any(
                type(metrics.get(key)) is not int or metrics[key] < 0
                for key in ("executed", "skipped", "failed")
            )
        ):
            return outcome("blocked", "verification_unavailable")
        if metrics["executed"] == 0:
            return outcome("blocked", "empty_test_suite")
        if metrics["failed"] != 0 or result.exit_code != 0:
            return outcome("failed", "verification_failed")
    if spec.profile == "python_script" and spec.expected_stdout is None:
        return outcome("blocked", "expected_output_missing")
    if spec.expected_stdout is not None:
        if not stdout_matches(result.stdout, spec.expected_stdout):
            return outcome("failed", "unexpected_output")
    return outcome("passed")


def stdout_matches(actual, expected):
    actual = actual.replace("\r\n", "\n")
    expected = expected.replace("\r\n", "\n")
    # A plain expected text line may omit print's one newline. An explicitly
    # supplied newline (or empty output) is exact; never strip extra blank lines.
    return actual == expected or (
        bool(expected) and not expected.endswith("\n") and actual == expected + "\n"
    )
