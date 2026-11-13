"""Bounded experimental fragment population execution and auditable artifacts."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from service.application.population.runner import run_fragment_population
from service.domain.contracts.population.fragment import FragmentPopulationConfig
from service.domain.target_response_limits import can_capture_targets, network_sample_ticks
from service.infrastructure.stimulation.population.archive import (
    load_verified_fragment_population,
)
from service.infrastructure.stimulation.population.diagnostics import fragment_edge_schedule
from service.infrastructure.stimulation.population.preview import (
    fragment_population_preview,
)
from service.infrastructure.stimulation.population.sparse_delta import (
    encode_sparse_delta,
    validate_sparse_snapshots,
)
from service.infrastructure.stimulation.population.target_response import (
    ARRAY_NAMES,
    encode_target_response,
    encode_target_response_binary,
    expected_direct_targets,
)


def _encoded(value):
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf8")


@dataclass
class FragmentPopulationExecution:
    graph: object
    synapse_index: object
    morphology_directories: list[Path]

    def execute(self, config: FragmentPopulationConfig, output: Path, *, contact_receipt=None,
                progress=None):
        if self.graph.provenance.get("manifest_sha256") != config.graph_manifest_sha256:
            raise ValueError("Requested graph does not match registered graph")
        output.mkdir(parents=True, exist_ok=True)
        paths = [
            output / name
            for name in (
                "signals.npz",
                "model.json",
                "source-provenance.jsonl",
                "fragment-population-preview.json",
                "fragment-events.bin",
                "manifest.json",
            )
        ]
        response_path = output / 'fragment-response.npz'
        response_binary_path = output / 'fragment-response.bin'
        sparse_path = output / 'fragment-delta.bin'
        if any(path.exists() for path in
               [*paths, response_path, response_binary_path, sparse_path]):
            raise FileExistsError("Fragment population result already exists")
        provenance = io.BytesIO()
        result = run_fragment_population(
            self.graph,
            self.synapse_index,
            self.morphology_directories,
            **config.execution_parameters(),
            provenance_sink=provenance,
            **({'progress': progress} if progress is not None else {}),
        )
        if 'experimental_solver_backend' in result:
            raise ValueError('Experimental solver results cannot be published')
        recording, wrapped = result["recording"], result["network"]
        network = wrapped["network"]
        diagnostics = result["diagnostics"]
        if (
            not isinstance(diagnostics, list)
            or len(diagnostics) != len(config.source_ids)
            or any(not isinstance(item, dict) for item in diagnostics)
            or [item.get("body_id") for item in diagnostics]
            != [str(body) for body in config.source_ids]
        ):
            raise ValueError("Incomplete fragment diagnostics")
        schedules = [
            fragment_edge_schedule(
                item,
                max_distance_um=config.max_distance_um,
                duration_ms=int(config.simulation.duration_ms),
                allow_partial_geometry=config.allow_partial_geometry is True,
            )
            for item in diagnostics
        ]
        if wrapped.get("schedules") != schedules or any(
            item["graph_sha256"] != config.graph_manifest_sha256 for item in schedules
        ):
            raise ValueError("Fragment schedules do not match source diagnostics")
        target_response = wrapped.get('target_response')
        response_bytes = None
        response_binary = None
        response_metadata = None
        arrays_response = None
        if target_response is not None:
            if not isinstance(target_response, dict):
                raise ValueError('Invalid target response')
            network_scope = target_response.get('scope') == 'network-excluding-forced-sources'
            if target_response.get('scope') not in (None, 'network-excluding-forced-sources'):
                raise ValueError('Unknown target response scope')
            network_ids = self.graph.ids if network_scope else None
            excluded = set(config.source_ids)
            targets = ([int(body) for body in network_ids if int(body) not in excluded]
                       if network_scope else expected_direct_targets(schedules, config.source_ids))
            duration = int(config.simulation.duration_ms)
            ticks = network_sample_ticks(len(targets), duration) if network_scope else None
            fits = (ticks is not None if network_scope
                    else can_capture_targets(len(targets), duration))
            expected_status = ('no_direct_targets' if not targets else 'recorded'
                               if fits else 'target_limit_exceeded')
            if (not isinstance(target_response, dict)
                    or target_response.get('status') != expected_status
                    or target_response.get('target_count') != len(targets)):
                raise ValueError('Target response coverage mismatch')
            response_metadata = {'status': expected_status, 'target_count': len(targets),
                                 'graph_sha256': config.graph_manifest_sha256,
                                 'configuration_sha256': config.digest(), 'seed': config.seed,
                                 'limit_policy': 'samples-4000000-v1'}
            if network_scope:
                response_metadata['scope'] = 'network-excluding-forced-sources'
                if ticks is not None and len(ticks) != duration + 1:
                    response_metadata['sample_times_ms'] = ticks
            if expected_status == 'recorded':
                arrays_response = {name: np.asarray(target_response[name]) for name in ARRAY_NAMES}
                if (not np.array_equal(target_response['delta_relative_mv'],
                                       arrays_response['active_relative_mv']
                                       - arrays_response['control_relative_mv'])):
                    raise ValueError('Target response difference mismatch')
                response_bytes = encode_target_response(
                    arrays_response, schedules=schedules, source_ids=config.source_ids,
                    duration_ms=int(config.simulation.duration_ms), network_ids=network_ids,
                )
                response_binary = encode_target_response_binary(
                    arrays_response, schedules=schedules, source_ids=config.source_ids,
                    duration_ms=int(config.simulation.duration_ms),
                    graph_sha256=config.graph_manifest_sha256, configuration_sha256=config.digest(),
                    network_ids=network_ids,
                )
                response_metadata['format'] = ('paired-lif-network-v3' if network_scope
                                               and len(ticks) != duration + 1
                                               else 'paired-lif-network-v2' if network_scope
                                               else 'paired-lif-targets-v1')
        sparse = network.get('sparse_delta')
        sparse_bytes = None
        sparse_metadata = None
        if sparse is not None:
            if (not isinstance(sparse, dict)
                    or sparse.get('status') not in ('recorded', 'limit_exceeded')):
                raise ValueError('Invalid sparse response')
            sparse_metadata = {'status': sparse['status'],
                               'graph_sha256': config.graph_manifest_sha256,
                               'configuration_sha256': config.digest()}
            if sparse['status'] == 'recorded':
                sparse_bytes = encode_sparse_delta(
                    sparse, graph=self.graph, source_ids=config.source_ids,
                    duration_ms=int(config.simulation.duration_ms),
                    configuration_sha256=config.digest())
                if arrays_response is None or not network_scope:
                    raise ValueError('Sparse response requires network snapshots')
                validate_sparse_snapshots(sparse, arrays_response, self.graph)
                sparse_metadata.update({'format': 'sparse-lif-delta-v1',
                                        'entries': len(sparse['values'])})
        time = np.asarray(recording["time_ms"], dtype=np.float64)
        arrays = {
            name: np.asarray(recording[name], dtype=np.float64)
            for name in ("neural_uv", "stimulus_artifact_uv", "total_uv", "stimulus_fraction")
        }
        neurons, times = np.asarray(network["spike_neurons"]), np.asarray(network["spike_times_ms"])
        if (
            time.ndim != 1
            or len(time) < 2
            or time[0] != 0
            or not np.isfinite(time).all()
            or np.any(np.diff(time) <= 0)
            or abs(time[-1] - config.simulation.duration_ms) > 1e-9
            or any(
                value.shape != time.shape or not np.isfinite(value).all()
                for value in arrays.values()
            )
            or np.any(np.abs(arrays["stimulus_fraction"]) > 1.0 + 1e-9)
            or not np.allclose(
                arrays["total_uv"],
                arrays["neural_uv"] + arrays["stimulus_artifact_uv"],
                rtol=1e-12,
                atol=1e-12,
            )
            or neurons.ndim != 1
            or neurons.dtype.kind not in "iu"
            or times.shape != neurons.shape
            or not np.isfinite(times).all()
            or np.any(neurons < 0)
            or np.any(neurons >= self.graph.size)
            or np.any(times < 1)
            or np.any(times > config.simulation.duration_ms)
            or np.isin(neurons, np.searchsorted(self.graph.ids, config.source_ids)).any()
        ):
            raise ValueError("Invalid fragment population recording or graph output")
        provenance_bytes = provenance.getvalue()
        try:
            proof_rows = [json.loads(line) for line in provenance_bytes.splitlines()]
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid fragment source provenance") from exc
        if (
            not recording.get("cell_provenance_exported")
            or not recording.get("cell_provenance_fields_present")
            or recording.get("cells") != len(config.source_ids)
            or recording.get("cell_provenance_sha256")
            != hashlib.sha256(provenance_bytes).hexdigest()
            or len(proof_rows) != len(diagnostics)
            or any(
                not isinstance(proof, dict)
                or proof.get("body_id") != item["body_id"]
                or proof.get("morphology_sha256") != item.get("morphology_sha256")
                for proof, item in zip(proof_rows, diagnostics, strict=True)
            )
            or wrapped["source_ids"] != config.source_ids
        ):
            raise ValueError("Incomplete fragment source provenance")
        metadata = {
            "configuration": config.model_dump(mode="json"),
            "configuration_sha256": config.digest(),
            "source_ids": config.source_ids,
            "contact_screen": contact_receipt,
            "coverage": result["coverage"],
            "interpretation": result["interpretation"],
            "recording": {
                key: value
                for key, value in recording.items()
                if key
                not in {
                    "time_ms",
                    "neural_uv",
                    "stimulus_artifact_uv",
                    "total_uv",
                    "stimulus_fraction",
                }
            },
            "diagnostics": result["diagnostics"],
            "schedules": wrapped["schedules"],
            "events": {"format": "fragment-events-v1", "graph_sha256": config.graph_manifest_sha256,
                       "node_count": self.graph.size, "event_count": len(neurons)},
        }
        if response_metadata is not None:
            metadata['target_response'] = response_metadata
        if sparse_metadata is not None:
            metadata['sparse_delta'] = sparse_metadata
        with paths[0].open("xb") as stream:
            np.savez_compressed(
                stream, time_ms=time, **arrays, spike_neurons=neurons, spike_times_ms=times
            )
        paths[1].write_bytes(_encoded(metadata))
        paths[2].write_bytes(provenance_bytes)
        preview = fragment_population_preview(
            {"time_ms": time, **arrays, "spike_times_ms": times},
            source_count=len(config.source_ids),
            duration_ms=int(config.simulation.duration_ms),
            edge_event_count=sum(
                event["count"] for schedule in schedules for event in schedule["edge_events"]
            ),
            unresolved_graph_pairs=(sum(len(schedule.get("unresolved_geometry", []))
                                        for schedule in schedules)
                                    if config.allow_partial_geometry is True else None),
        )
        paths[3].write_bytes(_encoded(preview))
        paths[4].write_bytes(
            np.asarray(self.graph.ids, dtype="<u8").tobytes()
            + np.asarray(neurons, dtype="<i4").tobytes()
            + np.asarray(times, dtype="<f4").tobytes()
        )
        if response_bytes is not None:
            response_path.write_bytes(response_bytes)
            response_binary_path.write_bytes(response_binary)
        if sparse_bytes is not None:
            sparse_path.write_bytes(sparse_bytes)
        with np.load(paths[0], allow_pickle=False) as stored:
            if (
                not np.array_equal(stored["time_ms"], time)
                or any(not np.array_equal(stored[key], value) for key, value in arrays.items())
                or not np.array_equal(stored["spike_neurons"], neurons)
                or not np.array_equal(stored["spike_times_ms"], times)
            ):
                raise ValueError("Fragment result archive did not round-trip")
        files = [
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in paths[:-1]
        ]
        if response_bytes is not None:
            files.append({'name': response_path.name, 'bytes': len(response_bytes),
                          'sha256': hashlib.sha256(response_bytes).hexdigest()})
            files.append({'name': response_binary_path.name, 'bytes': len(response_binary),
                          'sha256': hashlib.sha256(response_binary).hexdigest()})
        if sparse_bytes is not None:
            files.append({'name': sparse_path.name, 'bytes': len(sparse_bytes),
                          'sha256': hashlib.sha256(sparse_bytes).hexdigest()})
        manifest = {
            "kind": "experimental-fragment-population",
            "configuration_sha256": config.digest(),
            "graph_sha256": config.graph_manifest_sha256,
            "files": files,
            "coverage": result["coverage"],
            "interpretation": result["interpretation"],
        }
        paths[-1].write_bytes(_encoded(manifest))
        load_verified_fragment_population(output, self.graph)
        return manifest
