import base64
import logging
import mimetypes
from typing import Any
from uuid import UUID

from service.infrastructure.agents_client.ports import ANON_USER_UUID, resolve_user_uuid

logger = logging.getLogger(__name__)

# Официальный MIME для .pptx — один неразрывный токен в 71 символ. Внутри литерала
# места для переноса нет, поэтому вынесен в константу, а не спрятан под `noqa`.
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


# resolve_user_uuid/ANON_USER_UUID переехали в service.infrastructure.agents_client.ports: они нужны
# ОБЕИМ
# сторонам (backend адресует ими файлы, домен — выборку файлов пользователя), и ради
# чистой функции никто не должен тащить чужой пакет. Здесь ре-экспорт для прежних вызовов.


def _collect_candidate_user_uuids(user_id: str | int | UUID | None) -> list[UUID]:
    """Compatibility projection: Library artifacts require one real owner."""
    owner = resolve_user_uuid(user_id, anonymous_fallback=False)
    return [owner] if owner is not None and owner != ANON_USER_UUID else []


async def _save_with_fallback(
    *, file_service, user_uuid_candidates, user_id, filename: str, content: bytes, label: str
):
    """Compatibility signature; alternate owners are never admitted."""
    # Персист — забота BACKEND'а (worker-side), не движка: ServiceType (модель БД) и
    # RepositoryIntegrityError (repo-слой) тянут service.* — импортим ЛЕНИВО, чтобы
    # модуль оставался module-level переносимым в сайдкар.
    from service.models.key_value import ServiceType
    from service.shared.repositories.exceptions import RepositoryIntegrityError

    user_uuid_candidates = _collect_candidate_user_uuids(user_id)
    if not user_uuid_candidates:
        raise RepositoryIntegrityError("Artifact owner unavailable")
    saved = None
    for candidate_user_uuid in user_uuid_candidates:
        try:
            saved = await file_service.save(
                user_id=candidate_user_uuid,
                mode=ServiceType.CHAT,
                file_name=filename,
                file_content=content,
            )
            break
        except RepositoryIntegrityError:
            logger.warning(
                "artifact ownership persistence unavailable",
                extra={"component": "artifact", "failure_code": "persistence"},
            )
            continue
    if saved is None:
        raise RepositoryIntegrityError("Artifact persistence unavailable")
    return saved


async def _persist_one_artifact(
    art: dict[str, Any], *, file_service, user_uuid_candidates, user_id, job_id: str, idx: int
) -> dict[str, Any] | None:
    """Персист ОДНОГО артефакта (pptx, картинка или файл из песочницы) → generated_files."""
    file_b64 = art.get("file_b64")
    if isinstance(file_b64, str) and file_b64.strip():
        # ⚠️ Произвольный файл: тип НЕ угадываем по содержимому, берём по расширению. Файл
        # создал агент по просьбе пользователя, и имя — единственное, о чём они условились.
        try:
            filename = str(art.get("filename") or f"artifact_{job_id}_{idx}")
            content = base64.b64decode(file_b64, validate=True)
            lowered = filename.lower()
            if lowered.endswith(".pdf") and (
                not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]
            ):
                raise ValueError("invalid_pdf_artifact")
            if lowered.endswith((".zip", ".pptx")) and not content.startswith(b"PK\x03\x04"):
                raise ValueError("invalid_zip_artifact")
            if art.get("required"):
                from service.infrastructure.agents_client.required_artifacts import save_required

                saved = await save_required(file_service, user_id, job_id, filename, content)
            else:
                saved = await _save_with_fallback(
                    file_service=file_service,
                    user_uuid_candidates=user_uuid_candidates,
                    user_id=user_id,
                    filename=filename,
                    content=content,
                    label="FILE",
                )
            return {
                "kind": "file",
                "file_id": str(saved.file_id),
                "file_url": saved.file_url,
                "file_key": saved.file_key,
                "filename": filename,
                "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
            }
        except Exception:
            logger.warning(
                "artifact persistence failure",
                extra={"component": "workspace_artifact", "failure_code": "persist"},
            )
            return None

    pptx_b64 = art.get("pptx_b64")
    if isinstance(pptx_b64, str) and pptx_b64.strip():
        try:
            pptx_bytes = base64.b64decode(pptx_b64)
            filename = str(art.get("filename") or f"presentation_{job_id}_{idx}.pptx")
            if not filename.lower().endswith(".pptx"):
                filename = f"{filename}.pptx"
            saved = await _save_with_fallback(
                file_service=file_service,
                user_uuid_candidates=user_uuid_candidates,
                user_id=user_id,
                filename=filename,
                content=pptx_bytes,
                label="PPTX",
            )
            return {
                "kind": "presentation",
                "file_id": str(saved.file_id),
                "file_url": saved.file_url,
                "file_key": saved.file_key,
                "filename": filename,
                "mime_type": _PPTX_MIME,
            }
        except Exception:
            logger.warning(
                "artifact persistence failure",
                extra={"component": "presentation", "failure_code": "persist"},
            )
            return None

    image_b64 = art.get("b64_json")
    if isinstance(image_b64, str) and image_b64.strip():
        try:
            image_bytes = base64.b64decode(image_b64)
            # Индекс в имени — иначе несколько картинок одного хода делят одно имя.
            filename = f"image_{job_id}_{idx}.png"
            saved = await _save_with_fallback(
                file_service=file_service,
                user_uuid_candidates=user_uuid_candidates,
                user_id=user_id,
                filename=filename,
                content=image_bytes,
                label="image",
            )
            # Пресайн-URL (публичный S3, напр. Selectel) — чтобы <img> в чате
            # грузил картинку напрямую: сырой s3://-ключ браузер не отрисует.
            image_url = saved.file_url
            try:
                presigned = await file_service.get_presigned_url_by_key(file_key=saved.file_key)
                if isinstance(presigned, str) and presigned.startswith(("http://", "https://")):
                    image_url = presigned
            except Exception:
                logger.debug(
                    "artifact projection failure",
                    extra={"component": "image", "failure_code": "presign"},
                )
            return {
                "kind": "image",
                "file_id": str(saved.file_id),
                "file_url": image_url,
                "file_key": saved.file_key,
                "filename": filename,
                "mime_type": "image/png",
            }
        except Exception:
            logger.warning(
                "artifact persistence failure",
                extra={"component": "image", "failure_code": "persist"},
            )
            return None
    return None


async def persist_generated_artifacts(
    *,
    file_service,
    user_id: str | int | UUID | None,
    metadata: dict[str, Any] | None,
    job_id: str,
) -> tuple[str | None, dict[str, Any]]:
    """Persist binary artifacts produced by agent into storage and return updated metadata.

    Поддерживаемые payload'ы:
    - pptx_b64 (+ optional filename), b64_json (image bytes) — ОДИНОЧНЫЙ артефакт
      (обычный субагент кладёт их прямо в metadata);
    - _pending_artifacts: [{pptx_b64|b64_json, filename}, ...] — НЕСКОЛЬКО артефактов
      (мульти-интент). Singular-ключи затирали бы друг друга при слиянии metadata, из-за
      чего юзер платил за N генераций, а получал 1 (аудит A4). Теперь персистим КАЖДЫЙ.
    """
    if not isinstance(metadata, dict):
        return None, metadata or {}

    user_uuid_candidates = _collect_candidate_user_uuids(user_id)

    out = dict(metadata)

    # Список артефактов к персисту: мульти-интентные (список) + одиночный (singular).
    artifacts: list[dict[str, Any]] = [
        art for art in (out.get("_pending_artifacts") or []) if isinstance(art, dict)
    ]
    if out.get("pptx_b64") or out.get("b64_json"):
        artifacts.append(
            {
                "pptx_b64": out.get("pptx_b64"),
                "b64_json": out.get("b64_json"),
                "filename": out.get("filename"),
            }
        )

    generated_files: list[dict[str, Any]] = []
    for idx, art in enumerate(artifacts if user_uuid_candidates else []):
        entry = await _persist_one_artifact(
            art,
            file_service=file_service,
            user_uuid_candidates=user_uuid_candidates,
            user_id=user_id,
            job_id=job_id,
            idx=idx,
        )
        if entry:
            generated_files.append(entry)

    # Remove heavy inline blobs from metadata after persistence.
    out.pop("pptx_b64", None)
    out.pop("b64_json", None)
    out.pop("_pending_artifacts", None)

    if generated_files:
        existing = out.get("generated_files")
        out["generated_files"] = (existing if isinstance(existing, list) else []) + generated_files

    primary_file_url = generated_files[0]["file_url"] if generated_files else None
    return primary_file_url, out
