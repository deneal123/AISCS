"""Boot identity must change with profile templates, manifests and shared styles."""

import shutil

import pytest
from domain.documents import runtime_digest


@pytest.mark.parametrize(
    "relative",
    [
        "aaai_conference/main.tex",
        "aaai_conference/profile.toml",
        "_shared/gpthub-core.sty",
    ],
)
def test_runtime_identity_includes_profile_data(tmp_path, relative):
    root = runtime_digest._SERVICE_ROOT
    for name in runtime_digest._RUNTIME_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    data = tmp_path / "domain/documents/profile_data"
    shutil.copytree(root / "domain/documents/profile_data", data)
    before = runtime_digest.compute_document_runtime_digest(tmp_path)
    target = data / relative
    target.write_bytes(target.read_bytes() + b"\n% acceptance-change\n")
    assert runtime_digest.compute_document_runtime_digest(tmp_path) != before


def test_runtime_identity_includes_new_profile_asset(tmp_path):
    root = runtime_digest._SERVICE_ROOT
    for name in runtime_digest._RUNTIME_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    before = runtime_digest.compute_document_runtime_digest(tmp_path)
    target = tmp_path / "domain/documents/profile_data/example/extra.sty"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"% fixture")
    assert runtime_digest.compute_document_runtime_digest(tmp_path) != before


def test_runtime_identity_includes_project_manifest_reader(tmp_path):
    root = runtime_digest._SERVICE_ROOT
    names = {*runtime_digest._RUNTIME_FILES, "application/documents/projects.py"}
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    before = runtime_digest.compute_document_runtime_digest(tmp_path)
    target = tmp_path / "application/documents/projects.py"
    target.write_bytes(target.read_bytes() + b"\n# acceptance-change\n")
    assert runtime_digest.compute_document_runtime_digest(tmp_path) != before


@pytest.mark.parametrize("relative", ["application/lifecycle.py", "drivers/docker_cli.py"])
def test_runtime_identity_includes_operation_and_driver_boundaries(tmp_path, relative):
    root = runtime_digest._SERVICE_ROOT
    for name in {*runtime_digest._RUNTIME_FILES, relative}:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    before = runtime_digest.compute_document_runtime_digest(tmp_path)
    target = tmp_path / relative
    target.write_bytes(target.read_bytes() + b"\n# acceptance-change\n")
    assert runtime_digest.compute_document_runtime_digest(tmp_path) != before
