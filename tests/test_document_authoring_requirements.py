"""Final audit must read unresolved requirements, even if TeX omits them."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def runner():
    path = Path(__file__).parents[1] / "docker/document_runner.py"
    spec = importlib.util.spec_from_file_location("authoring_requirements_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(tmp_path, fields):
    draft = {"version": 1, "blocks": [{"kind": "section", "title": "Signatures"}]}
    raw = {
        "schema_version": 1,
        "draft_version": 1,
        "profile_id": "ru_legal_a4",
        "draft": draft,
        "draft_digest": hashlib.sha256(
            json.dumps(draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "intent": {"required_sections": ["Signatures"], "legal_fields": fields},
    }
    (tmp_path / ".gpthub-authoring.json").write_text(json.dumps(raw), encoding="utf-8")
    return raw


@pytest.mark.parametrize("value", [None, "", "  \n "])
def test_unresolved_critical_requirement_blocks_final_even_when_tex_omits_it(tmp_path, value):
    manifest(tmp_path, [{"name": "party", "value": value, "required": True}])
    assert runner().authoring_manifest_audit(tmp_path, "ru_legal_a4") == [
        {"severity": "error", "code": "unresolved_placeholder", "count": 1}
    ]


@pytest.mark.parametrize(
    "fields",
    [
        None,
        {},
        [None],
        [{"name": "party", "value": None, "required": "false"}],
        [{"name": "party", "value": {"private": "body"}, "required": True}],
        [{"name": "", "value": None, "required": True}],
        [{"name": "party", "value": None, "required": True}] * 33,
    ],
)
def test_invalid_requirement_shape_is_a_bounded_audit_failure(tmp_path, fields):
    manifest(tmp_path, fields)
    assert runner().authoring_manifest_audit(tmp_path, "ru_legal_a4") == [
        {"severity": "error", "code": "authoring_invalid", "count": 1}
    ]


@pytest.mark.parametrize(
    "changed", [{"draft": None}, {"draft": []}, {"draft_version": True}, {"schema_version": True}]
)
def test_invalid_authoring_shape_never_escapes_as_an_exception(tmp_path, changed):
    raw = manifest(tmp_path, [])
    raw.update(changed)
    (tmp_path / ".gpthub-authoring.json").write_text(json.dumps(raw), encoding="utf-8")
    assert runner().authoring_manifest_audit(tmp_path, "ru_legal_a4") == [
        {"severity": "error", "code": "authoring_invalid", "count": 1}
    ]


def test_resolved_and_optional_fields_do_not_block(tmp_path):
    manifest(
        tmp_path,
        [
            {"name": "party", "value": "Synthetic fixture party", "required": True},
            {"name": "optional", "value": None, "required": False},
        ],
    )
    assert runner().authoring_manifest_audit(tmp_path, "ru_legal_a4") == []


def test_preview_retains_unresolved_requirements_as_warnings(tmp_path):
    manifest(tmp_path, [{"name": "party", "value": None, "required": True}])
    assert runner().authoring_manifest_audit(tmp_path, "ru_legal_a4", False) == [
        {"severity": "warning", "code": "unresolved_placeholder", "count": 1}
    ]
