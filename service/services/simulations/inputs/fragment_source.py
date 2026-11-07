"""Resolve only owned, internally consistent fragment-population artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from service.models.db.db_models import UserFile
from service.services.simulations.inputs.fragment_package import ALLOWED, OwnedFragmentFile
from service.services.simulations.models import SimulationArtifact, SimulationRun


class FragmentSourceUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class OwnedFragmentSource:
    manifest: dict
    files: list[OwnedFragmentFile]
    configuration: dict


async def owned_fragment_source(session, user_id: UUID, run_id: UUID, graph_sha256: str):
    run = (await session.execute(select(SimulationRun).where(
        SimulationRun.id == run_id, SimulationRun.user_id == user_id
    ))).scalar_one_or_none()
    if run is None or run.state != 'completed' or not isinstance(run.result, dict):
        raise FragmentSourceUnavailable('source_unavailable')
    manifest = run.result.get('manifest')
    if (not isinstance(graph_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', graph_sha256)
            or not isinstance(manifest, dict)
            or manifest.get('kind') != 'experimental-fragment-population'
            or manifest.get('graph_sha256') != graph_sha256
            or manifest.get('configuration_sha256') != run.configuration_sha256
            or not isinstance(run.configuration, dict)
            or run.configuration.get('graph_manifest_sha256') != graph_sha256
            or not isinstance(manifest.get('files'), list)):
        raise FragmentSourceUnavailable('source_graph_mismatch')
    entries = manifest['files']
    if (tuple(row.get('name') if isinstance(row, dict) else None for row in entries) not in ALLOWED
            or any(set(row) != {'name', 'bytes', 'sha256'}
                   or type(row['bytes']) is not int or row['bytes'] <= 0
                   or not isinstance(row['sha256'], str)
                   or not re.fullmatch(r'[a-f0-9]{64}', row['sha256']) for row in entries)):
        raise FragmentSourceUnavailable('source_artifact_invalid')
    rows = (await session.execute(select(SimulationArtifact, UserFile)
        .join(UserFile, UserFile.id == SimulationArtifact.file_id)
        .where(SimulationArtifact.run_id == run_id, UserFile.user_id == user_id))).all()
    by_name = {artifact.name: (artifact, file) for artifact, file in rows}
    if len(rows) != len(entries) or len(by_name) != len(entries):
        raise FragmentSourceUnavailable('source_artifact_missing')
    files = []
    for entry in entries:
        row = by_name.get(entry['name'])
        if row is None:
            raise FragmentSourceUnavailable('source_artifact_missing')
        artifact, file = row
        if (artifact.sha256 != entry['sha256'] or artifact.size != entry['bytes']
                or artifact.file_id != file.id or not isinstance(file.file_name, str)
                or not file.file_name):
            raise FragmentSourceUnavailable('source_artifact_mismatch')
        files.append(OwnedFragmentFile(name=entry['name'], storage_key=file.file_name,
                                       size=entry['bytes'], sha256=entry['sha256']))
    return OwnedFragmentSource(manifest=manifest, files=files, configuration=run.configuration)
