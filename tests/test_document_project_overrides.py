"""Editable profile fields remain typed, bounded and reflected in run policy."""

import base64
import json
import tomllib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.projects import DocumentProjectError, DocumentProjectService, _toml
from domain.documents import load_profile_catalog
from domain.documents.project_validation import update_project_mode


def service(profile_id="generic_document", **changes):
    catalog = load_profile_catalog()
    profile = catalog.get(profile_id)
    raw = {**tomllib.loads(_toml(profile, mode="draft", locale="ru-RU")), **changes}
    lines = []
    for key, value in raw.items():
        if isinstance(value, bool):
            rendered = str(value).lower()
        elif isinstance(value, str):
            rendered = json.dumps(value)
        else:
            rendered = repr(value).replace("'", '"')
        lines.append(f"{key} = {rendered}")
    encoded = base64.b64encode("\n".join(lines).encode()).decode()

    async def run(_item, command, **_kwargs):
        return SimpleNamespace(stdout="__MISSING__" if "effective-profile" in command else encoded)

    item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"))
    return DocumentProjectService(run, AsyncMock(), catalog), item


@pytest.mark.parametrize(
    "changes",
    [
        {"paper": "PRIVATE_UNSUPPORTED"},
        {"orientation": "PRIVATE_UNSUPPORTED"},
        {"schema_version": True},
        {"profile_version": True},
        {"bibliography_required": 0},
        {"locale": 'ru"\nengine="unsafe'},
    ],
)
@pytest.mark.asyncio
async def test_invalid_manifest_cannot_disable_policy(changes):
    instance, item = service(**changes)
    with pytest.raises(DocumentProjectError) as result:
        await instance.manifest(item, "documents/fixture")
    assert result.value.code in {"invalid_project", "profile_mismatch"}
    assert "PRIVATE" not in str(result.value)


@pytest.mark.parametrize("value", [-1, True, "8", 1.5, 10001])
@pytest.mark.asyncio
async def test_page_limit_is_a_bounded_integer(value):
    instance, item = service("generic_article", max_pages=value)
    with pytest.raises(DocumentProjectError):
        await instance.manifest(item, "documents/fixture")


@pytest.mark.parametrize("value", [0, 9])
@pytest.mark.asyncio
async def test_publisher_page_limit_cannot_be_weakened(value):
    instance, item = service("aaai_conference", max_pages=value)
    with pytest.raises(DocumentProjectError):
        await instance.manifest(item, "documents/fixture")


@pytest.mark.asyncio
async def test_valid_override_is_reflected_in_resolved_profile():
    instance, item = service(paper="letter", orientation="landscape")
    raw, resolved = await instance.manifest(item, "documents/fixture")
    assert (resolved.paper, resolved.orientation) == (raw["paper"], raw["orientation"])
    assert instance.catalog.get("generic_document").paper == "a4"


@pytest.mark.asyncio
async def test_valid_page_limit_is_reflected_without_mutating_catalog():
    instance, item = service("generic_article", max_pages=12)
    _, resolved = await instance.manifest(item, "documents/fixture")
    assert resolved.max_pages == 12
    assert instance.catalog.get("generic_article").max_pages is None


@pytest.mark.asyncio
async def test_invalid_locale_does_not_create_project_or_snapshot():
    instance, item = service()
    instance._run = AsyncMock(return_value=SimpleNamespace(stdout="__OK__"))
    with pytest.raises(DocumentProjectError):
        await instance.create(
            item,
            path="documents/new",
            profile_id="generic_document",
            mode="draft",
            locale='ru"\nengine="unsafe',
        )
    instance._run.assert_not_called()
    instance._snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_same_profile_mode_update_preserves_all_other_settings():
    instance, item = service(paper="letter", orientation="landscape")
    original_read = instance._run
    written = []

    async def run(item, command, *, stdin_payload=None):
        if stdin_payload is not None:
            written.append(tomllib.loads(base64.b64decode(stdin_payload).decode()))
            return SimpleNamespace(stdout="__OK__")
        result = await original_read(item, command)
        if result.stdout != "__MISSING__":
            text = base64.b64decode(result.stdout).decode()
            result.stdout = base64.b64encode(
                (text + '\nuser_note = "preserve custom metadata"\n').encode()
            ).decode()
        return result

    instance._run = run
    await instance.apply_profile(
        item,
        path="documents/fixture",
        profile_id="generic_document",
        mode="camera_ready",
    )
    assert written[0]["paper"] == "letter"
    assert written[0]["orientation"] == "landscape"
    assert written[0]["user_note"] == "preserve custom metadata"
    assert written[0]["mode"] == "camera_ready"
    instance._snapshot.assert_awaited_once()


def test_mode_update_preserves_comments_and_nested_user_data():
    text = (
        "mode = 'draft' # retain this comment\nlocale = \"ru-RU\"\nanonymize = false\n"
        '[custom]\ncaption="mode = draft, locale = ru-RU"\n'
    )
    updated = update_project_mode(text, mode="camera_ready", locale="en-US", anonymize=False)
    assert "# retain this comment" in updated
    assert '[custom]\ncaption="mode = draft, locale = ru-RU"' in updated
    assert tomllib.loads(updated)["locale"] == "en-US"


@pytest.mark.parametrize("mode", ['"mode" = "draft"', 'mode = """draft"""'])
def test_noncanonical_manifest_edit_is_rejected_not_reconstructed(mode):
    text = mode + '\nlocale="ru-RU"\nanonymize=false\n'
    with pytest.raises(ValueError, match="^invalid_project$"):
        update_project_mode(text, mode="camera_ready", locale="ru-RU", anonymize=False)
