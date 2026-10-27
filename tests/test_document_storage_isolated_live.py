"""Opt-in real MinIO outage at FileSaver; repository is fake, no vision/outbox claim."""

import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import time
import uuid
from urllib.request import urlopen

import pytest
from urllib3.exceptions import HTTPError

from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.models.key_value import ServiceType
from service.services.files.application.file_saver_service import FileSaverService
from service.settings import MinioConfig


def _docker(*args, env=None):
    result = subprocess.run(
        ["docker", *args], capture_output=True, timeout=30, check=False, env=env
    )
    if result.returncode:
        raise RuntimeError("isolated_storage_docker_failed")
    return result.stdout.decode().strip()


def _wait_ready(endpoint):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://{endpoint}/minio/health/ready", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("isolated_storage_not_ready")


class _Repository:
    """No production database changes; count successful metadata admissions only."""

    def __init__(self):
        self.rows = {}

    async def fetch_user_file_by_upload_intent(self, owner, intent):
        return self.rows.get((owner, intent))

    async def add_file_metadata(self, row):
        row.id = uuid.uuid4()
        self.rows[(row.user_id, row.upload_intent_id)] = row
        return row


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_ISOLATED_STORAGE") != "1", reason="isolated Docker MinIO acceptance"
)
async def test_streamed_artifact_recovers_after_isolated_minio_outage():
    identity = uuid.uuid4().hex
    name = f"gpthub-s37-storage-{identity}"
    label = f"gpthub.s37.storage={identity}"
    environment = dict(os.environ)
    environment["MINIO_ROOT_USER"] = f"s37{identity}"
    environment["MINIO_ROOT_PASSWORD"] = secrets.token_hex(24)
    created = False
    storage = None
    try:
        # Docker can assign a different ephemeral HostPort after stop/start.
        # Reserve an explicit loopback port so the existing client is tested
        # against the same endpoint through the outage, not rebuilt afterward.
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            host_port = reservation.getsockname()[1]
        image = _docker("inspect", "gpthub-dev-minio-1", "--format", "{{.Image}}")
        assert image.startswith("sha256:")
        _docker(
            "create",
            "--name",
            name,
            "--label",
            label,
            "--publish",
            f"127.0.0.1:{host_port}:9000",
            "--network",
            "bridge",
            "--env",
            "MINIO_ROOT_USER",
            "--env",
            "MINIO_ROOT_PASSWORD",
            image,
            "server",
            "/data",
            env=environment,
        )
        created = True
        _docker("start", name)
        ports = json.loads(_docker("inspect", name, "--format", "{{json .NetworkSettings.Ports}}"))
        binding = ports["9000/tcp"][0]
        assert binding["HostIp"] == "127.0.0.1"
        endpoint = f"127.0.0.1:{int(binding['HostPort'])}"
        await asyncio.to_thread(_wait_ready, endpoint)
        storage = await asyncio.to_thread(
            MinioFileStorage,
            MinioConfig(
                endpoint=endpoint,
                access_key=environment["MINIO_ROOT_USER"],
                secret_key=environment["MINIO_ROOT_PASSWORD"],
                bucket="s37-isolated",
                region="us-east-1",
                secure=False,
                public_endpoint="",
                retry_attempts=1,
                retry_backoff=0,
                presign_expiry=60,
            ),
        )
        repository = _Repository()
        files = FileSaverService(repository=repository, folder_name="uploads", file_storage=storage)
        owner, intent = uuid.uuid4(), uuid.uuid4()
        # Synthetic bytes exercise integrity/storage, not PDF compiler acceptance.
        payload = b"synthetic-storage-acceptance\n" * 80000
        digest = hashlib.sha256(payload).hexdigest()

        async def chunks():
            for offset in range(0, len(payload), 65536):
                yield payload[offset : offset + 65536]

        async def save():
            return await files.save_stream(
                owner,
                ServiceType.CHAT,
                "storage-acceptance.pdf",
                chunks(),
                expected_size=len(payload),
                expected_sha256=digest,
                upload_intent_id=intent,
            )

        await asyncio.to_thread(_docker, "stop", "--time", "2", name)
        with pytest.raises((HTTPError, OSError)):
            await save()
        assert not repository.rows, "failed upload must not acknowledge a Library record"
        await asyncio.to_thread(_docker, "start", name)
        await asyncio.to_thread(_wait_ready, endpoint)
        first = await save()
        assert not first.reused and len(repository.rows) == 1
        replay = await save()
        assert replay.reused and replay.file_id == first.file_id
        assert len(repository.rows) == 1
        response = await asyncio.to_thread(
            storage._client.get_object, storage._bucket, first.file_key
        )
        try:
            received = hashlib.sha256()
            size = 0
            for chunk in response.stream(65536):
                received.update(chunk)
                size += len(chunk)
            assert received.hexdigest() == digest and size == len(payload)
        finally:
            response.close()
            response.release_conn()
        assert len(list(storage._client.list_objects(storage._bucket, recursive=True))) == 1
    finally:
        if storage is not None:
            storage._client._http.clear()
        if created:
            # Only this exact, labelled, freshly created container can be removed.
            actual = _docker(
                "inspect", name, "--format", '{{index .Config.Labels "gpthub.s37.storage"}}'
            )
            assert actual == identity
            _docker("rm", "--force", "--volumes", name)
