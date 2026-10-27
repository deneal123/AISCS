"""Server-issued admission and idempotent publication of direct uploads."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException

from service.models.db.db_models import UserFile
from service.models.key_value import ServiceType
from service.settings import config

_NAMESPACE = "file_upload_admission"
logger = logging.getLogger(__name__)


class AdmissionRevoked(RuntimeError):
    """Private typed failure: an in-flight publication lost its admission."""


def _identity(value: Any) -> UUID:
    try:
        result = UUID(str(value))
        if result.int:
            return result
    except (ValueError, TypeError, AttributeError):
        pass
    raise HTTPException(404, "Upload not found")


def _source_key(saver: Any, owner: UUID, file_id: UUID, mode: ServiceType, name: str) -> str:
    return saver.storage.build_file_path(
        saver.folder, mode.value, f"pending/{owner.hex}/{file_id.hex}{Path(name).suffix.lower()}"
    )


async def issue(saver: Any, user_id: Any, mode: ServiceType, name: str, expiry: int | None) -> dict:
    owner = _identity(user_id)
    safe_name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (
        not safe_name
        or len(safe_name) > 1000
        or not any(
            safe_name.lower().endswith(ext.lower())
            for ext in config.file.settings.allowed_extensions
        )
    ):
        raise HTTPException(400, "Invalid file extension")
    if saver.upload_cache is None:
        raise HTTPException(503, "Upload unavailable")
    file_id = uuid4()
    key = _source_key(saver, owner, file_id, mode, safe_name)
    ttl = min(3600, max(1, expiry if expiry is not None else 3600))
    try:
        url = await saver.storage.get_presigned_upload_url(file_key=key, expiry_sec=ttl)
        if not isinstance(url, str) or any(ord(char) < 33 for char in url):
            raise ValueError()
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError()
        _ = parsed.port
        await saver.upload_cache.set_json(
            _NAMESPACE,
            str(file_id),
            {
                "owner": str(owner),
                "mode": mode.value,
                "key": key,
                "name": safe_name,
                "expires_at": time.time() + ttl,
            },
            ttl_seconds=ttl,
        )
    except Exception:
        raise HTTPException(503, "Upload unavailable") from None
    return {"file_id": file_id, "file_key": key, "upload_url": url, "expires_in": ttl}


def _replay(saver: Any, row: Any, owner: UUID, file_id: UUID, mode: ServiceType, key: str) -> dict:
    if (
        row.upload_intent_id != file_id
        or row.type != mode
        or _source_key(saver, owner, file_id, mode, row.original_name or "") != key
    ):
        raise HTTPException(404, "Upload not found")
    return {"file_id": row.id, "file_url": row.file_url}


async def _enqueue_scan(saver: Any, row: Any) -> None:
    if saver.message_bus is None:
        return
    namespace, identifier = "file_upload_scan", str(row.id)
    try:
        if saver.upload_cache is not None:
            marker = await saver.upload_cache.get_json(namespace, identifier)
            if isinstance(marker, dict) and marker.get("enqueued") is True:
                return
    except Exception:
        # Missing acknowledgement must not silently prevent scan redelivery.
        pass
    try:
        await saver.message_bus.push("file:scan:queue", row.file_name)
        if saver.upload_cache is not None:
            await saver.upload_cache.set_json(
                namespace, identifier, {"enqueued": True}, ttl_seconds=86400
            )
    except Exception:
        logger.debug(
            "file scan enqueue unavailable",
            extra={"component": "file_scan", "failure_code": "transport"},
        )


async def _settle_cancelled_copy(
    saver: Any, owner: UUID, file_id: UUID, destination: str, cleanup_allowed: bool
) -> None:
    """Resolve lost commit acknowledgement without abandoning recovery on disconnect."""

    async def settle() -> None:
        safe_to_delete = cleanup_allowed
        if not safe_to_delete:
            try:
                async with asyncio.timeout(10):
                    row = await saver.repository.fetch_user_file_by_id(owner, file_id)
                safe_to_delete = row is None or row.file_name != destination
            except Exception:
                # Unknown commit state is not evidence that the object is orphaned.
                safe_to_delete = False
        if safe_to_delete:
            await saver._cleanup_cancelled_upload(destination)

    recovery = asyncio.create_task(settle())
    while not recovery.done():
        try:
            await asyncio.shield(recovery)
        except asyncio.CancelledError:
            continue
    recovery.result()


async def finalize(saver: Any, user_id: Any, mode: ServiceType, file_id: Any, key: str) -> dict:
    owner, file_id = _identity(user_id), _identity(file_id)
    try:
        row = await saver.repository.fetch_user_file_by_id(owner, file_id)
    except Exception:
        raise HTTPException(503, "Upload unavailable") from None
    if row is not None:
        result = _replay(saver, row, owner, file_id, mode, key)
        await _enqueue_scan(saver, row)
        return result
    if saver.upload_cache is None:
        raise HTTPException(503, "Upload unavailable")
    try:
        offer = await saver.upload_cache.get_json(_NAMESPACE, str(file_id))
    except Exception:
        raise HTTPException(503, "Upload unavailable") from None
    if not isinstance(offer, dict) or (
        offer.get("owner") != str(owner)
        or offer.get("mode") != mode.value
        or offer.get("key") != key
    ):
        raise HTTPException(404, "Upload not found")
    try:
        expires_at = float(offer["expires_at"])
        if not math.isfinite(expires_at) or expires_at <= time.time():
            raise HTTPException(404, "Upload not found")
        name = offer["name"]
        if not isinstance(name, str) or _source_key(saver, owner, file_id, mode, name) != key:
            raise HTTPException(404, "Upload not found")
    except (KeyError, ValueError, TypeError):
        raise HTTPException(404, "Upload not found") from None

    # The browser can still PUT to its issued key until expiry. Publish a private,
    # verified copy, never mutable browser-controlled bytes as a permanent source.
    destination = saver.storage.build_file_path(
        saver.folder, mode.value, saver._generate_file_name(name)
    )
    cleanup_allowed = True
    try:
        await saver.storage.commit_presigned_upload(
            source_key=key,
            destination_key=destination,
            max_bytes=config.file.settings.max_file_size_byte,
        )
        url = await saver.get_presigned_url_by_key(file_key=destination)
        if url is None:
            raise HTTPException(503, "Upload unavailable")
        metadata = UserFile(
            id=file_id,
            user_id=owner,
            type=mode,
            file_name=destination,
            file_url=url,
            original_name=name,
            upload_intent_id=file_id,
        )
        try:
            cleanup_allowed = False

            async def verify_admission() -> bool:
                current = await saver.upload_cache.get_json(_NAMESPACE, str(file_id))
                if (
                    not isinstance(current, dict)
                    or any(
                        current.get(field) != offer.get(field)
                        for field in ("owner", "mode", "key", "name", "expires_at")
                    )
                    or expires_at <= time.time()
                ):
                    return False
                return True

            guarded_writer = getattr(saver.repository, "add_direct_file_metadata", None)
            if callable(guarded_writer):
                saved = await guarded_writer(metadata, verify_admission)
                if saved is None:
                    raise AdmissionRevoked("upload_admission_revoked")
            else:
                # Compatibility repositories used by older internal callers.
                if not await verify_admission():
                    raise AdmissionRevoked("upload_admission_revoked")
                saved = await saver.repository.add_file_metadata(metadata)
        except Exception:
            # A lost DB acknowledgement is not proof of rollback. Bound this
            # exact-owner read; timeout leaves cleanup disallowed and retains
            # a potentially committed Library object for an explicit retry.
            async with asyncio.timeout(30):
                recovered = await saver.repository.fetch_user_file_by_id(owner, file_id)
            if recovered is None:
                cleanup_allowed = True
                raise
            result = _replay(saver, recovered, owner, file_id, mode, key)
            if recovered.file_name != destination:
                await saver._delete_uploaded_object(destination)
            await _enqueue_scan(saver, recovered)
            return result
    except asyncio.CancelledError:
        # Commit acknowledgement can be lost on disconnect; do not delete an
        # object already referenced by a successfully committed row.
        await _settle_cancelled_copy(saver, owner, file_id, destination, cleanup_allowed)
        raise
    except AdmissionRevoked:
        if cleanup_allowed:
            await saver._delete_uploaded_object(destination)
        raise HTTPException(404, "Upload not found") from None
    except Exception:
        if cleanup_allowed:
            await saver._delete_uploaded_object(destination)
        raise HTTPException(503, "Upload unavailable") from None
    await _enqueue_scan(saver, saved)
    return {"file_id": saved.id, "file_url": saved.file_url}
