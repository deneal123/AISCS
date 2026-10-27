"""Pre-seal protocol repair is bounded across restarts by existing durable grants."""

from types import SimpleNamespace

import pytest

from service.services.chat.persistence.harness.grants import precontract_limit_reached


@pytest.mark.parametrize("count,expected", [(0, False), (1, False), (2, True), (3, True)])
def test_no_new_contract_prompt_can_reset_the_original_plus_one_repair_limit(count, expected):
    grants = [{"request": {"kind": "meta_usage"}, "state": "succeeded"}] * count
    assert (
        precontract_limit_reached({"checkpoint": None}, SimpleNamespace(kind="meta_usage"), grants)
        is expected
    )


@pytest.mark.parametrize("kind", ["chat", "route_model", "pdf_authoring"])
def test_other_paid_stages_do_not_spend_the_contract_protocol_repair_allowance(kind):
    grants = [{"request": {"kind": kind}}] * 4
    assert not precontract_limit_reached(
        {"checkpoint": None}, SimpleNamespace(kind="meta_usage"), grants
    )


def test_sealed_task_metadata_is_not_a_new_contract_attempt():
    grants = [{"request": {"kind": "meta_usage"}}] * 5
    assert not precontract_limit_reached(
        {"checkpoint": {"state": {}}}, SimpleNamespace(kind="meta_usage"), grants
    )
