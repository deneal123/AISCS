"""Authenticated internal RPC must explicitly reject ambient routing and redirects."""

import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "workspace_client.py",
        "workspace_documents.py",
        "agents_client/http_agent_engine.py",
    ],
)
def test_all_internal_client_constructors_have_explicit_network_policy(module):
    source = Path(__file__).parents[1] / "service/infrastructure" / module
    tree = ast.parse(source.read_text(encoding="utf-8"))
    constructors = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "AsyncClient"
    ]
    assert constructors
    for node in constructors:
        keywords = {kw.arg: kw.value for kw in node.keywords}
        for name in ("trust_env", "follow_redirects"):
            assert isinstance(keywords.get(name), ast.Constant), (module, node.lineno, name)
            assert keywords[name].value is False, (module, node.lineno, name)
