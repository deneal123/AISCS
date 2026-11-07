"""Application boundary for replaying a previously authorized network result."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from service.domain.contracts.replay_contract import ReplayRunConfig
from service.infrastructure.stimulation.replay_export import export_reference_replay
from service.infrastructure.stimulation.synaptic_replay import execute_all_incoming_replay


@dataclass
class ReplayRecordedCell:
    graph: object
    synapse_index: object
    morphology_directories: list[Path]

    def execute(self, config: ReplayRunConfig, *, source_run_id: UUID, source_binary: bytes,
                source_description: dict, source_sha256: str, output: Path, progress=None):
        """Replay a source selected and authorized by the caller.

        Backend must authenticate ownership and obtain the digest from its
        trusted run manifest. This component never accepts user-supplied paths.
        """
        if source_run_id != config.source_run_id:
            raise ValueError("Replay source run differs from authorized source")
        if (self.graph.provenance["manifest_sha256"] != config.graph_manifest_sha256
                or source_description.get("manifest_sha256") != config.graph_manifest_sha256):
            raise ValueError("Replay graph differs from authorized source")
        plan = config.execution_parameters()
        result = execute_all_incoming_replay(
            self.synapse_index, self.graph, config.body_id, self.morphology_directories,
            binary=source_binary, description=source_description, expected_sha256=source_sha256,
            schedule_parameters=plan["schedule_parameters"],
            simulation_parameters=plan["simulation_parameters"],
            electrode_um=plan["electrode_um"], reference_um=plan["reference_um"],
            source_model=plan["source_model"], progress=progress,
        )
        result["request"] = {"source_run_id": str(source_run_id),
                             "configuration_sha256": config.digest(),
                             "configuration": config.model_dump(mode="json")}
        manifest = export_reference_replay(result, output)
        return {"source_run_id": str(source_run_id), "configuration_sha256": config.digest(),
                "manifest": manifest, "interpretation": result["interpretation"]}
