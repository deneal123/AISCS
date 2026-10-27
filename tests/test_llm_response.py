"""Canonical content access never renders a provider object's representation."""

from types import SimpleNamespace

import pytest

from service.domain.llm_response import first_message_content


@pytest.mark.parametrize(
    "response",
    [
        {"choices": [{"message": {"content": "Привет!"}}]},
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Привет!"))]),
        {"choices": (SimpleNamespace(message={"content": "Привет!"}),)},
    ],
)
def test_response_content_supports_sdk_and_decoded_shapes(response):
    assert first_message_content(response) == "Привет!"


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"choices": []},
        {"choices": "PRIVATE_RESPONSE"},
        {"choices": {"message": {"content": "PRIVATE_RESPONSE"}}},
        {"choices": [None]},
        {"choices": [{"message": None}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": {"private_state": "PRIVATE_RESPONSE"}}}]},
        {"choices": [{"message": {"content": ["PRIVATE_RESPONSE"]}}]},
        {"choices": [{"message": {"content": 42}}]},
    ],
)
def test_unknown_response_shape_returns_no_content(response):
    assert first_message_content(response) == ""


def test_non_text_content_is_never_stringified():
    class PrivateContent:
        def __str__(self):
            pytest.fail("private provider content was stringified")

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=PrivateContent()))]
    )
    assert first_message_content(response) == ""


def test_missing_content_does_not_fall_back_to_tool_arguments_or_other_choices():
    response = {
        "choices": [
            {"message": {"content": None, "tool_calls": [{"arguments": "PRIVATE_ARGUMENTS"}]}},
            {"message": {"content": "not the selected choice"}},
        ]
    }
    assert first_message_content(response) == ""
