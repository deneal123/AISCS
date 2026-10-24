"""Детерминированные проверки публикации модели без загрузки настоящих весов."""

import hashlib
import io
from dataclasses import replace
from unittest.mock import Mock

import pytest

from local_llm.service.domain.model import MODEL
from local_llm.service.infrastructure.models import artifacts
from local_llm.service.infrastructure.models.artifacts import (
    ArtifactUnavailable,
    download,
    verified,
)


@pytest.fixture
def model(monkeypatch):
    body = b"synthetic-gguf"
    artifact = replace(MODEL, size=len(body), sha256=hashlib.sha256(body).hexdigest())
    open_url = Mock(side_effect=lambda *args, **kwargs: io.BytesIO(body))
    monkeypatch.setattr(artifacts.urllib.request, "urlopen", open_url)
    return artifact, open_url


def test_publish_only_verified_file_and_reuse_without_network(tmp_path, model):
    artifact, open_url = model
    path = download(artifact, tmp_path)
    assert verified(path, artifact)
    assert download(artifact, tmp_path) == path
    open_url.assert_called_once()
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("fault", ["digest", "oversized", "truncated"])
def test_bad_download_never_becomes_model_or_leaves_lock(tmp_path, model, fault):
    artifact, _ = model
    if fault == "digest":
        artifact = replace(artifact, sha256="0" * 64)
    else:
        artifact = replace(artifact, size=artifact.size + (1 if fault == "truncated" else -1))
    with pytest.raises(ArtifactUnavailable):
        download(artifact, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_unknown_existing_model_is_not_overwritten_or_downloaded(tmp_path, model):
    artifact, open_url = model
    target = tmp_path / artifact.filename
    target.write_bytes(b"previous-model")
    with pytest.raises(ArtifactUnavailable, match="cache_conflict"):
        download(artifact, tmp_path)
    assert target.read_bytes() == b"previous-model"
    open_url.assert_not_called()


def test_unknown_downloader_does_not_allow_parallel_download(tmp_path, model):
    artifact, open_url = model
    lock = tmp_path / (artifact.filename + ".lock")
    lock.write_text("previous-intent", encoding="utf-8")
    with pytest.raises(ArtifactUnavailable, match="busy"):
        download(artifact, tmp_path)
    assert lock.read_text(encoding="utf-8") == "previous-intent"
    open_url.assert_not_called()


def test_network_failure_has_no_private_diagnostic_and_releases_owned_lock(tmp_path, model):
    artifact, open_url = model
    open_url.side_effect = RuntimeError("PRIVATE_SIGNED_URL")
    with pytest.raises(ArtifactUnavailable, match="model_download_unavailable") as caught:
        download(artifact, tmp_path)
    assert "PRIVATE_SIGNED_URL" not in str(caught.value)
    assert list(tmp_path.iterdir()) == []
