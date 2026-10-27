"""Платная приёмка блокируется до транспорта и не повторяет неизвестный вызов."""

from types import SimpleNamespace

import httpx

from scripts.memory_acceptance.guard import PaidGuard


class Pricing:
    def price(self, calls):
        return SimpleNamespace(credits=2)


def guard(ceiling):
    return PaidGuard(
        key="synthetic",
        pricing=Pricing(),
        ceiling=ceiling,
        profile={"embedding": [{"provider": "a", "model": "embed"}]},
    )


def test_insufficient_budget_never_reaches_provider(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kw: (_ for _ in ()).throw(AssertionError("paid")))
    probe = guard(1)
    status, _ = probe.forward("/v1/embeddings", {"model": "gpthub-memory-embedding", "input": "x"})
    assert status == 402
    assert probe.used == 0


def test_unknown_ack_consumes_ceiling_and_is_not_retried(monkeypatch):
    seen = []

    def transport(request):
        seen.append(1)
        raise httpx.ReadTimeout("synthetic")

    client = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(httpx, "Client", lambda **kw: client)
    probe = guard(3)
    payload = {"model": "gpthub-memory-embedding", "input": "x"}
    assert probe.forward("/v1/embeddings", payload)[0] == 502
    assert probe.used == probe.unknown == 2
    assert probe.forward("/v1/embeddings", payload)[0] == 402
    assert seen == [1]
