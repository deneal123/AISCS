"""A lost metadata commit acknowledgement must not delete a committed file."""

import hashlib
from uuid import uuid4

import pytest

from service.models.key_value import ServiceType
from service.services.files.application.file_saver_service import FileSaverService


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming,with_intent", [(False, False), (False, True), (True, True)])
@pytest.mark.parametrize("resolution", ["committed", "absent", "unavailable", "mismatch"])
async def test_upload_compensation_resolves_commit_before_deleting_object(
    streaming, with_intent, resolution, caplog
):
    owner, intent = uuid4(), uuid4()
    body = b"synthetic artifact"
    marker = "private-commit-ack-marker"

    class Repository:
        row = None

        async def fetch_user_file_by_upload_intent(self, *_args):
            return self.row

        async def add_file_metadata(self, row):
            row.id = uuid4()
            if resolution in {"committed", "mismatch"}:
                self.row = row
                if resolution == "mismatch":
                    row.content_sha256 = "0" * 64
            raise RuntimeError(marker)

        async def fetch_user_file_by_name(self, user_id, key):
            assert user_id == owner and key == "uploads/CHAT/opaque.pdf"
            if resolution == "unavailable":
                raise RuntimeError(marker)
            return self.row

    class Storage:
        deleted = []

        def build_file_path(self, *_args):
            return "uploads/CHAT/opaque.pdf"

        async def upload_file(self, **_kwargs):
            return "internal://object"

        async def upload_file_stream(self, **kwargs):
            assert kwargs["stream"].read() == body
            return "internal://object"

        async def delete_file(self, *, file_key):
            self.deleted.append(file_key)

    async def chunks():
        yield body

    repository, storage = Repository(), Storage()
    service = FileSaverService(repository, "uploads", storage)
    if streaming:
        call = service.save_stream(
            owner,
            ServiceType.CHAT,
            "final.pdf",
            chunks(),
            expected_size=len(body),
            expected_sha256=hashlib.sha256(body).hexdigest(),
            upload_intent_id=intent,
        )
    else:
        call = service.save(
            owner,
            ServiceType.CHAT,
            "final.pdf",
            body,
            upload_intent_id=intent if with_intent else None,
        )
    if resolution == "committed":
        result = await call
        assert result.file_id == repository.row.id and result.reused
    else:
        with pytest.raises((RuntimeError, ValueError)):
            await call
    assert storage.deleted == (["uploads/CHAT/opaque.pdf"] if resolution == "absent" else [])
    assert marker not in caplog.text
