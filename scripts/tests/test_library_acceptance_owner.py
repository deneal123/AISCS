"""Acceptance preparation stays read-only and restricted to explicit dev actors."""

import ast
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "library_browser_smoke",
    Path(__file__).parents[1] / "smoke_library_download_browser.py",
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
_owned_probe = smoke._owned_probe


@pytest.mark.parametrize("owner", ["s37", "s38"])
def test_actor_selection_changes_only_the_declared_fixture_email(owner):
    source = "SELECT owner WHERE email='s37-e2e-391e5206659a3654@example.com'"
    result = _owned_probe(source, owner)
    expected = (
        source
        if owner == "s37"
        else source.replace(
            "s37-e2e-391e5206659a3654@example.com", "s38-video-acceptance@example.com"
        )
    )
    assert result == expected


@pytest.mark.parametrize("owner", ["other", "", "production@example.com"])
def test_arbitrary_actors_cannot_mint_a_browser_fixture(owner):
    with pytest.raises(ValueError, match="invalid_acceptance_fixture"):
        _owned_probe("s37-e2e-391e5206659a3654@example.com", owner)


@pytest.mark.parametrize("source", ["", "s37-e2e-391e5206659a3654@example.com" * 2])
def test_probe_drift_fails_closed(source):
    with pytest.raises(ValueError, match="invalid_acceptance_fixture"):
        _owned_probe(source, "s38")


def test_current_sql_fixture_remains_read_only_after_actor_selection():
    path = (
        Path(__file__).parents[2]
        / "backend/tests/test_document_library_download_live.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_PROBE"
            for target in node.targets
        )
    )
    source = _owned_probe(ast.literal_eval(assignment.value), "s38")
    ast.parse(source)
    assert "s38-video-acceptance@example.com" in source
    assert not any(
        word in source for word in ("INSERT", "UPDATE", "DELETE", "create_session")
    )
