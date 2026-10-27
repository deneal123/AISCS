"""Предохранитель платной приёмки проверяется без внешних запросов."""

from types import SimpleNamespace

import httpx

from scripts.image_generation_live import MODEL, ImageCallGuard


def guard():
    return ImageCallGuard(
        SimpleNamespace(
            routerai_base_url="https://fixture-router/v1",
            gigachat_base_url="https://fixture-giga/v1",
            gigachat_oauth_url="https://fixture-auth/oauth",
        )
    )


def test_guard_permits_only_one_exact_image_request():
    policy = guard()
    request = httpx.Request(
        "POST", "https://fixture-router/v1/images", json={"model": MODEL, "n": 1}
    )
    assert policy.allows(request)
    assert not policy.allows(request)
    assert policy.image_calls == 1


def test_guard_rejects_another_model_endpoint_or_image_count_before_charging():
    policy = guard()
    for url, body in [
        ("https://fixture-router/v1/images", {"model": "other-model", "n": 1}),
        ("https://fixture-router/v1/images", {"model": MODEL, "n": 2}),
        ("https://fixture-router/v1/chat/completions", {"model": MODEL}),
        ("https://unapproved/v1/images", {"model": MODEL, "n": 1}),
    ]:
        assert not policy.allows(httpx.Request("POST", url, json=body))
    assert policy.image_calls == 0


def test_guard_bounds_text_calls_and_never_admits_unknown_read_hosts():
    policy = guard()
    request = httpx.Request(
        "POST", "https://fixture-giga/v1/chat/completions", json={"model": "GigaChat-3-Lightning"}
    )
    assert all(policy.allows(request) for _ in range(4))
    assert not policy.allows(request)
    assert not policy.allows(httpx.Request("GET", "https://unapproved/billable-operation"))
