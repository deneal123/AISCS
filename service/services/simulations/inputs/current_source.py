"""Resolve a completed owned current archive from registered run and file records."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from service.models.db.db_models import UserFile
from service.services.simulations.manifests.field_graph_manifest import (
    InvalidFieldGraphManifest,
    validate_field_graph_manifest,
)
from service.services.simulations.models import SimulationArtifact, SimulationRun


class CurrentSourceUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class CurrentSource:
    storage_key: str
    sha256: str
    size: int
    manifest_sha256: str
    configuration: dict


async def owned_current_source(session, user_id: UUID, run_id: UUID):
    run = (
        await session.execute(
            select(SimulationRun).where(
                SimulationRun.id == run_id, SimulationRun.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if (
        run is None
        or run.state != "completed"
        or not isinstance(run.result, dict)
        or not isinstance(run.configuration, dict)
        or run.configuration.get("retain_currents") is not True
    ):
        raise CurrentSourceUnavailable("source_unavailable")
    manifest = run.result.get("manifest")
    try:
        validate_field_graph_manifest(
            manifest, configuration_sha256=run.configuration_sha256, retain_currents=True
        )
    except InvalidFieldGraphManifest as exc:
        raise CurrentSourceUnavailable("source_manifest_invalid") from exc
    entry = next(item for item in manifest["files"] if item["name"] == "currents.zip")
    row = (
        await session.execute(
            select(SimulationArtifact, UserFile)
            .join(UserFile, UserFile.id == SimulationArtifact.file_id)
            .where(
                SimulationArtifact.run_id == run_id,
                SimulationArtifact.name == "currents.zip",
                UserFile.user_id == user_id,
            )
        )
    ).first()
    if row is None:
        raise CurrentSourceUnavailable("source_artifact_missing")
    artifact, file = row
    if (
        artifact.sha256 != entry["sha256"]
        or artifact.size != entry["bytes"]
        or artifact.file_id != file.id
        or not isinstance(file.file_name, str)
        or not file.file_name
    ):
        raise CurrentSourceUnavailable("source_artifact_mismatch")
    return CurrentSource(
        file.file_name,
        artifact.sha256,
        artifact.size,
        manifest["current_manifest_sha256"],
        run.configuration,
    )
