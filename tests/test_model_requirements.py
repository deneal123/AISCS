from __future__ import annotations

import pytest

from service.domain.client import registry
from service.domain.client.model_requirements import ModelRequirement


def test_requirement_detects_tools_and_nested_image_blocks() -> None:
    requirement = ModelRequirement.from_call(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect"},
                    {"type": "image_url", "image_url": {"url": "opaque"}},
                ],
            }
        ],
        tools=[{"type": "function", "function": {"name": "read"}}],
    )

    assert requirement == ModelRequirement(chat=True, tools=True, vision=True)


@pytest.mark.asyncio
async def test_embedding_only_catalog_does_not_activate_static_chat_fallback(monkeypatch) -> None:
    class _EmbeddingOnlyProvider:
        @staticmethod
        async def list_available_models() -> list[str]:
            # A successful non-empty provider response is authoritative.  The static
            # fallback must only be supplied by ModelListCache when discovery fails.
            return ["Embeddings-2"]

    monkeypatch.setattr(registry, "get_provider_module", lambda _name: _EmbeddingOnlyProvider)

    selected = await registry.resolve_model_for("gigachat", prefer="GigaChat-2")

    assert selected is None


@pytest.mark.asyncio
async def test_vision_requirement_never_falls_back_to_blind_model(monkeypatch) -> None:
    class _Provider:
        @staticmethod
        async def list_available_models() -> list[str]:
            return ["vendor/text-chat"]

    async def _catalog() -> dict:
        return {"vendor/text-chat": {"capabilities": []}}

    monkeypatch.setattr(registry, "get_provider_module", lambda _name: _Provider)
    monkeypatch.setattr("service.shared.model_catalog.get_openrouter_catalog", _catalog)

    selected = await registry.resolve_model_for(
        "provider",
        prefer="vendor/vision-chat",
        requirement=ModelRequirement(vision=True),
    )

    assert selected is None


@pytest.mark.asyncio
async def test_tool_requirement_selects_only_confirmed_tool_model(monkeypatch) -> None:
    class _Provider:
        @staticmethod
        async def list_available_models() -> list[str]:
            return ["vendor/plain", "vendor/tools"]

    async def _supports(model: str) -> bool:
        return model == "vendor/tools"

    monkeypatch.setattr(registry, "get_provider_module", lambda _name: _Provider)
    monkeypatch.setattr("service.shared.model_catalog.model_supports_tools", _supports)

    selected = await registry.resolve_model_for(
        "provider",
        requirement=ModelRequirement(tools=True),
    )

    assert selected == "vendor/tools"
