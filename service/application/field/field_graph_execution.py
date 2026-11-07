"""Application boundary for an experimental electrical field-graph calculation."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from service.application.field.field_graph_replay import run_field_graph_replay
from service.domain.contracts.field_graph_contract import FieldGraphConfig
from service.infrastructure.stimulation.current_archive import (
    CurrentArchiveWriter,
    rerecord_current_archive,
)
from service.infrastructure.stimulation.field_graph_export import (
    export_field_graph_replay,
    load_verified_field_graph_replay,
)


@dataclass
class FieldGraphExecution:
    graph: object
    synapse_index: object
    morphology_directories: list[Path]

    def execute(
        self, config: FieldGraphConfig, output: Path, *, current_archive_output: Path | None = None
    ):
        if self.graph.provenance["manifest_sha256"] != config.graph_manifest_sha256:
            raise ValueError("Requested graph does not match registered graph")
        writer = None
        if current_archive_output is not None:
            if (
                current_archive_output.resolve() == output.resolve()
                or output.resolve() in current_archive_output.resolve().parents
                or current_archive_output.resolve() in output.resolve().parents
            ):
                raise ValueError(
                    "Current archive must be separate from the published result directory"
                )
            writer = CurrentArchiveWriter(
                current_archive_output,
                config.simulation.electrode_um,
                config.simulation.reference_um,
                source_model=config.simulation.source_model,
            )
        evidence, provenance = io.BytesIO(), io.BytesIO()
        result = run_field_graph_replay(
            self.synapse_index,
            self.graph,
            self.morphology_directories,
            **config.execution_parameters(),
            evidence_sink=evidence,
            provenance_sink=provenance,
            **({"solution_sink": writer.add} if writer is not None else {}),
        )
        archive_sha = None
        if writer is not None:
            expected_ids = [str(cell.body_id) for cell in config.source_cells] + [
                str(body) for body in config.replay_ids
            ]
            if [entry["body_id"] for entry in writer.entries] != expected_ids:
                raise ValueError("Current archive does not contain the requested cells in order")
            archive_sha = writer.finish()
            restored = rerecord_current_archive(
                current_archive_output,
                archive_sha,
                config.simulation.electrode_um,
                config.simulation.reference_um,
                source_model=config.simulation.source_model,
            )
            if not np.array_equal(restored["time_ms"], result["recording"]["time_ms"]) or any(
                not np.allclose(restored[name], result["recording"][name], rtol=1e-12, atol=1e-12)
                for name in ("neural_uv", "stimulus_artifact_uv", "total_uv")
            ):
                raise ValueError("Current archive does not reproduce the original recording")
        manifest = export_field_graph_replay(
            result,
            self.graph,
            output,
            evidence=evidence.getvalue(),
            provenance=provenance.getvalue(),
        )
        load_verified_field_graph_replay(output, self.graph)
        response = {
            "configuration_sha256": config.digest(),
            "manifest": manifest,
            "interpretation": result["interpretation"],
        }
        if archive_sha is not None:
            response["current_archive_sha256"] = archive_sha
        return response
