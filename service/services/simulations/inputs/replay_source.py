"""Resolve an owned, internally consistent source for isolated-cell replay."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from service.models.db.db_models import UserFile
from service.services.simulations.models import SimulationArtifact, SimulationRun


class ReplaySourceUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class ReplaySource:
    description: dict
    file_id: UUID
    storage_key: str
    sha256: str
    size: int


async def owned_replay_source(session, user_id: UUID, run_id: UUID, graph_sha256: str):
    run = (await session.execute(select(SimulationRun).where(
        SimulationRun.id == run_id, SimulationRun.user_id == user_id
    ))).scalar_one_or_none()
    if run is None or run.state != "completed" or not isinstance(run.result, dict):
        raise ReplaySourceUnavailable("source_unavailable")
    preview = run.result.get("preview")
    description = preview.get("connectome") if isinstance(preview, dict) else None
    manifest = run.result.get("manifest")
    if (not isinstance(description, dict) or not isinstance(manifest, dict)
            or not isinstance(graph_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", graph_sha256)
            or description.get("manifest_sha256") != graph_sha256
            or not isinstance(manifest.get("connectome"), dict)
            or manifest["connectome"].get("manifest_sha256") != graph_sha256
            or not isinstance(manifest.get("files"), list)):
        raise ReplaySourceUnavailable("source_graph_mismatch")
    entries = [item for item in manifest["files"]
               if isinstance(item, dict) and item.get("name") == "connectome.bin"]
    if len(entries) != 1:
        raise ReplaySourceUnavailable("source_artifact_missing")
    entry = entries[0]
    checksum, size = entry.get("sha256"), entry.get("bytes")
    if (not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum)
            or type(size) is not int or size <= 0 or not isinstance(description.get("binary"), dict)
            or description["binary"].get("bytes") != size):
        raise ReplaySourceUnavailable("source_artifact_invalid")
    row = (await session.execute(
        select(SimulationArtifact, UserFile)
        .join(UserFile, UserFile.id == SimulationArtifact.file_id)
        .where(SimulationArtifact.run_id == run_id, SimulationArtifact.name == "connectome.bin",
               UserFile.user_id == user_id)
    )).first()
    if row is None:
        raise ReplaySourceUnavailable("source_artifact_missing")
    artifact, file = row
    if artifact.sha256 != checksum or artifact.size != size or artifact.file_id != file.id:
        raise ReplaySourceUnavailable("source_artifact_mismatch")
    if not isinstance(file.file_name, str) or not file.file_name:
        raise ReplaySourceUnavailable("source_artifact_invalid")
    return ReplaySource(description=description, file_id=file.id, storage_key=file.file_name,
                        sha256=checksum, size=size)
