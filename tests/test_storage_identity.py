"""Namespace fingerprints name storage, not credentials, public URLs or health."""

from unittest.mock import patch

import pytest

from service.infrastructure.storage.identity import storage_identity
from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.settings import MinioConfig


def test_local_namespace_is_stable_for_the_same_resolved_root(tmp_path):
    first = LocalFileStorage(tmp_path / "first")
    same = LocalFileStorage(tmp_path / "first" / ".")
    other = LocalFileStorage(tmp_path / "second")
    assert first.namespace_id == same.namespace_id
    assert first.namespace_id != other.namespace_id
    assert str(tmp_path) not in first.namespace_id


@pytest.mark.parametrize(
    "change,same",
    [
        ({"access_key": "rotated-access", "secret_key": "rotated-secret"}, True),
        ({"public_endpoint": "https://public-fixture.invalid"}, True),
        ({"endpoint": "other-fixture.invalid:9000"}, False),
        ({"bucket": "other-fixture"}, False),
        ({"secure": True}, False),
    ],
)
def test_minio_namespace_has_no_network_probe_or_credential_identity(change, same):
    initial = MinioConfig(endpoint="fixture.invalid:9000", bucket="fixture", secure=False)
    changed = initial.model_copy(update=change)
    with patch("minio.Minio") as sdk:
        first, second = MinioFileStorage(initial), MinioFileStorage(changed)
        sdk.reset_mock()
        assert (first.namespace_id == second.namespace_id) is same
        sdk.assert_not_called()
        assert "rotated" not in second.namespace_id
        # Existing adapters keep the identity of their constructed SDK target.
        before = first.namespace_id
        initial.endpoint = "reconfigured.invalid:9000"
        assert first.namespace_id == before


@pytest.mark.parametrize(
    "kind,values",
    [
        ("unknown", ("root",)),
        ("local", ()),
        ("local", (None,)),
        ("minio", ("",)),
    ],
)
def test_invalid_locator_is_not_a_guessed_namespace(kind, values):
    with pytest.raises(ValueError, match="^storage_identity_invalid$"):
        storage_identity(kind, *values)


def test_length_delimited_identity_has_no_ambiguous_locator_concatenation():
    assert storage_identity("minio", "ab", "c") != storage_identity("minio", "a", "bc")
    assert storage_identity("local", "root") != storage_identity("minio", "root")
