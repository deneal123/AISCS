"""Real supervisor/framework output through backend HTTP, journal and snapshot storage."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_VERIFICATION_SERVICES_LIVE") != "1", reason="isolated verification opt-in"
)
@pytest.mark.parametrize(
    "case",
    [
        "unittest_pass",
        "unittest_fail",
        "empty",
        "skipped",
        "pytest_missing",
        "pytest_pass",
        "pytest_fail",
        "pytest_empty",
        "pytest_skipped",
        "stdout_extra",
        "truncated",
    ],
)
def test_framework_and_output_require_real_nonempty_successful_receipts(case):
    assert run_command_probe(verification_case=case)["verification_profile_verified"] == case
