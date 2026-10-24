"""Атомарная ограниченная загрузка; повреждённый файл не становится готовой моделью."""

import hashlib
import os
import tempfile
import time
import urllib.request
from pathlib import Path

from ...domain.model import Artifact


class ArtifactUnavailable(RuntimeError):
    """Безопасный отказ без публикации URL, путей или сетевой диагностики."""


def verified(path: Path, artifact: Artifact) -> bool:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != artifact.size:
        return False
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() == artifact.sha256


def download(artifact: Artifact, directory: Path, *, timeout: float = 900) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / artifact.filename
    if verified(target, artifact):
        return target
    if target.exists() or target.is_symlink():
        raise ArtifactUnavailable("model_cache_conflict")
    lock = directory / (artifact.filename + ".lock")
    temporary = None
    try:
        # Потерянный владелец требует явной сверки. TTL не разрешает второй downloader.
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ArtifactUnavailable("model_download_busy") from None
    try:
        os.close(descriptor)
        if verified(target, artifact):
            return target
        digest, size, deadline = hashlib.sha256(), 0, time.monotonic() + timeout
        descriptor, name = tempfile.mkstemp(prefix=".model-", suffix=".part", dir=directory)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as output:
            with urllib.request.urlopen(artifact.url, timeout=min(30, timeout)) as response:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > artifact.size or time.monotonic() > deadline:
                        raise ArtifactUnavailable("model_download_limit")
                    digest.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size != artifact.size or digest.hexdigest() != artifact.sha256:
            raise ArtifactUnavailable("model_digest_mismatch")
        # Нет перезаписи неизвестного файла: ошибка cache требует явного решения.
        if target.exists() or target.is_symlink():
            raise ArtifactUnavailable("model_cache_conflict")
        os.replace(temporary, target)
        temporary = None
        return target
    except ArtifactUnavailable:
        raise
    except Exception:
        raise ArtifactUnavailable("model_download_unavailable") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
