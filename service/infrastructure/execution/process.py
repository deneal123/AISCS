"""Single-executor process isolation, repeat delivery, durable receipts and explicit cleanup ack."""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import shutil
import signal
import tempfile
import threading
from pathlib import Path
from time import time
from uuid import UUID

from service.contracts import ExecutionRequest, SimulationConfig
from service.domain.contracts.field_graph_contract import FieldGraphExecutionRequest
from service.domain.contracts.field_proxy_contract import FieldProxyExecutionRequest
from service.domain.contracts.fragment_population_contract import FragmentPopulationExecutionRequest
from service.domain.contracts.population_feedback_contract import PopulationFeedbackExecutionRequest
from service.domain.contracts.population_target_contract import PopulationTargetExecutionRequest
from service.domain.contracts.replay_contract import ReplayExecutionRequest
from service.infrastructure.execution.replay_input import ReplayInputStore
from service.shared.json_io import write_json


def _write_progress(directory: Path, progress: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='progress-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(progress, stream)
        os.replace(name, directory / 'progress.json')
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _file_sha256(path: Path) -> str:
    """Hash artifacts incrementally without loading a full result into memory."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _valid_progress(progress):
    if not isinstance(progress, dict):
        return False
    phase, done, total = progress.get('phase'), progress.get('done'), progress.get('total')
    if type(done) is not int or type(total) is not int:
        return False
    if phase in ('feedback_network', 'feedback_cells'):
        if (set(progress) != {'phase', 'iteration', 'done', 'total'}
                or type(progress['iteration']) is not int or not 1 <= progress['iteration'] <= 100):
            return False
        return (done == total == 0 if phase == 'feedback_network'
                else 0 < done <= total <= 256)
    if phase == 'field':
        return (set(progress) == {'phase', 'done', 'total'}
                and 0 <= done <= total <= 166700 and total > 0)
    if phase == 'field_verification':
        return set(progress) == {'phase', 'done', 'total'} and done == total == 0
    if set(progress) != {'phase', 'done', 'total'}:
        return False
    return ((done == total == 0 or 0 <= done <= total <= 1000 and total > 0) if phase == 'network'
            else phase in ('geometry', 'cells') and 0 < done <= total <= 256)


def run_child(payload: dict, directory: str) -> None:
    from service.main import build_generation

    target = Path(directory)
    try:
        config = SimulationConfig.model_validate(payload)
        build_generation().execute(config, target)
    except Exception as exc:
        target.mkdir(parents=True, exist_ok=True)
        write_json(target / "error.json", {"type": type(exc).__name__, "message": str(exc)[:1000]})
        raise


def run_field_proxy_child(payload: dict, directory: str) -> None:
    """Isolate one uncalibrated field-proxy execution in its own process."""
    from service.application.field.field_proxy_execution import execute_field_proxy
    from service.infrastructure.connectome.neighbors import registered_graph
    from service.settings import morphology_directories

    target = Path(directory)
    work = target.parent / 'field-proxy-work'
    try:
        request = FieldProxyExecutionRequest.model_validate(payload)
        config = request.config
        graph = registered_graph()
        if graph.provenance.get('manifest_sha256') != config.graph_manifest_sha256:
            raise ValueError('Field-proxy graph mismatch')
        try:
            field_workers = int(os.environ.get('GENERATOR_FIELD_WORKERS', '1'))
        except ValueError as exc:
            raise ValueError('Invalid field worker count') from exc
        if not 1 <= field_workers <= 8:
            raise ValueError('Invalid field worker count')
        field_backend = os.environ.get('GENERATOR_FIELD_BACKEND', 'cpu')
        if field_backend not in {'cpu', 'gpu'}:
            raise ValueError('Invalid field backend')
        # multiprocessing daemon workers cannot create child processes. Keep
        # cancellation semantics intact and use the verified sequential path.
        if mp.current_process().daemon:
            field_workers = 1
        work.mkdir(parents=True, exist_ok=False)
        execute_field_proxy(graph, morphology_directories(), field_path=work / 'field.jsonl',
            output=target, configuration=config.field_configuration(), gain=config.gain,
            seed=config.seed, waveform=config.waveform, compute_field=True,
            allow_partial_geometry=config.allow_partial_geometry,
            allow_missing_curvature=config.allow_missing_curvature,
            allow_contact_exclusion=config.allow_contact_exclusion, capture_delta=True,
            field_workers=field_workers, field_backend=field_backend,
            progress=lambda value: _write_progress(target.parent, value))
        files = []
        for path in sorted(target.iterdir()):
            if path.is_file():
                files.append({'name': path.name, 'bytes': path.stat().st_size,
                              'sha256': _file_sha256(path)})
        write_json(target / 'manifest.json', {'format': 'field-proxy-manifest-v1',
            'kind': 'experimental-field-proxy',
            'configuration_sha256': config.digest(), 'files': files,
            'interpretation': 'uncalibrated network proxy; no physical recording'})
    except Exception as exc:
        target.mkdir(parents=True, exist_ok=True)
        write_json(target / 'error.json', {'type': type(exc).__name__, 'message': str(exc)[:1000]})
        raise
    finally:
        if work.is_dir() and not work.is_symlink():
            shutil.rmtree(work)


def run_field_proxy_group(payload: dict, directory: str) -> None:
    """Put one field calculation and its worker pool in an isolated POSIX group."""
    os.setsid()
    run_field_proxy_child(payload, directory)


def run_replay_child(payload: dict, directory: str, root: str) -> None:
    from service.application.replay.replay import ReplayRecordedCell
    from service.infrastructure.connectome.neighbors import registered_graph
    from service.infrastructure.connectome.synapse_repository import registered_index
    from service.infrastructure.stimulation.replay_preview import export_replay_preview
    from service.settings import connectome_directory, morphology_directories

    target = Path(directory)
    try:
        request = ReplayExecutionRequest.model_validate(payload)
        source_path = ReplayInputStore(Path(root)).path(request.execution_id)
        graph = registered_graph()
        synapse_root = os.environ.get("GENERATOR_SYNAPSE_DIR", "")
        if not synapse_root:
            raise ValueError("Synapse source is not configured")
        index = registered_index(Path(synapse_root), connectome_directory() / "ids.npy")
        application = ReplayRecordedCell(graph, index, morphology_directories())
        result = application.execute(
            request.config, source_run_id=request.config.source_run_id,
            source_binary=source_path.read_bytes(), source_description=request.source_description,
            source_sha256=request.source_sha256, output=target,
        )
        preview = export_replay_preview(target)
        write_json(target / "manifest.json", {**result["manifest"],
                   "files": [*result["manifest"]["files"], preview],
                   "kind": "independent-cell-replay",
                   "configuration_sha256": request.config.digest(),
                   "source_run_id": str(request.config.source_run_id)})
    except Exception as exc:
        target.mkdir(parents=True, exist_ok=True)
        write_json(target / "error.json", {"type": type(exc).__name__, "message": str(exc)[:1000]})
        raise


def run_field_graph_child(payload: dict, directory: str) -> None:
    from service.application.field.field_graph_execution import FieldGraphExecution
    from service.application.field.field_state_artifacts import bundle_field_state_contrast
    from service.infrastructure.connectome.neighbors import registered_graph
    from service.infrastructure.connectome.synapse_repository import registered_index
    from service.infrastructure.stimulation.current_transport import pack_current_archive
    from service.infrastructure.stimulation.field_graph_preview import export_field_graph_preview
    from service.settings import connectome_directory, morphology_directories

    target = Path(directory)
    try:
        request = FieldGraphExecutionRequest.model_validate(payload)
        synapse_root = os.environ.get("GENERATOR_SYNAPSE_DIR", "")
        if not synapse_root:
            raise ValueError("Synapse source is not configured")
        graph = registered_graph()
        index = registered_index(Path(synapse_root), connectome_directory() / "ids.npy")
        work = target.parent / "current-archive-work"
        try:
            result = FieldGraphExecution(graph, index, morphology_directories()).execute(
                request.config, target,
                **({"current_archive_output": work} if request.config.retain_currents else {}),
            )
            preview = export_field_graph_preview(target, graph)
            files = [*result["manifest"]["files"], preview]
            if request.config.retain_state_contrast:
                files.extend(bundle_field_state_contrast(
                    target, graph, duration_ms=int(request.config.simulation.duration_ms)))
            archive_fields = {}
            if request.config.retain_currents:
                package = pack_current_archive(work, result["current_archive_sha256"],
                                               target / "currents.zip")
                if package["bytes"] > 256 * 1024 * 1024:
                    raise ValueError("Current archive exceeds the artifact transport limit")
                files.append({"name": "currents.zip", "bytes": package["bytes"],
                              "sha256": package["sha256"]})
                archive_fields["current_manifest_sha256"] = package["manifest_sha256"]
            write_json(target / "manifest.json", {**result["manifest"], **archive_fields,
                       "files": files, "kind": "field-graph-replay",
                       "configuration_sha256": request.config.digest()})
        finally:
            if request.config.retain_currents and work.exists():
                shutil.rmtree(work)
    except Exception as exc:
        target.mkdir(parents=True, exist_ok=True)
        write_json(target / "error.json", {"type": type(exc).__name__, "message": str(exc)[:1000]})
        raise


def run_fragment_population_child(payload: dict, directory: str) -> None:
    from service.application.population.fragment_contact_preflight import (
        check_fragment_contacts,
        fragment_contact_receipt,
    )
    from service.application.population.fragment_population_execution import (
        FragmentPopulationExecution,
    )
    from service.infrastructure.connectome.neighbors import registered_graph
    from service.infrastructure.connectome.synapse_repository import registered_index
    from service.settings import connectome_directory, morphology_directories

    target = Path(directory)
    try:
        def progress(phase, done, total):
            _write_progress(target.parent, {'phase': phase, 'done': done, 'total': total})
        request = FragmentPopulationExecutionRequest.model_validate(payload)
        synapse_root = os.environ.get('GENERATOR_SYNAPSE_DIR', '')
        if not synapse_root:
            raise ValueError('Synapse source is not configured')
        graph = registered_graph()
        directories = morphology_directories()
        report = check_fragment_contacts(request.config, graph, directories)
        receipt = fragment_contact_receipt(request.config, graph, report)
        index = registered_index(Path(synapse_root), connectome_directory() / 'ids.npy')
        FragmentPopulationExecution(graph, index, directories).execute(
            request.config, target, contact_receipt=receipt, progress=progress)
    except Exception as exc:
        target.mkdir(parents=True, exist_ok=True)
        write_json(target / 'error.json', {'type': type(exc).__name__, 'message': str(exc)[:1000]})
        raise


def run_population_feedback_child(payload: dict, directory: str, input_root: str) -> None:
    """Run a coupled population from a verified, privately restored source package."""
    import tempfile

    from service.application.feedback.population_feedback_loop import iterate_population_feedback
    from service.application.feedback.population_feedback_preview import population_feedback_preview
    from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
    from service.infrastructure.connectome.forced_export import encode_forced_spikes
    from service.infrastructure.connectome.neighbors import registered_graph
    from service.infrastructure.connectome.synapse_repository import SOURCE_MD5, registered_index
    from service.infrastructure.stimulation.fragment_population_transport import (
        unpack_fragment_population,
    )
    from service.infrastructure.stimulation.fragment_sparse_delta import encode_sparse_delta
    from service.infrastructure.stimulation.population_feedback_archive import (
        read_population_feedback,
        write_population_feedback,
    )
    from service.infrastructure.stimulation.population_source_events import (
        encode_population_source_events,
    )
    from service.settings import connectome_directory, morphology_directories

    target = Path(directory)
    feedback_diagnostics = None
    try:
        request = PopulationFeedbackExecutionRequest.model_validate(payload)
        config = request.config
        package = ReplayInputStore(Path(input_root)).path(request.execution_id)
        synapse_root = os.environ.get('GENERATOR_SYNAPSE_DIR', '')
        if not synapse_root:
            raise ValueError('Synapse source is not configured')
        graph = registered_graph()
        if graph.provenance.get('manifest_sha256') != config.graph_manifest_sha256:
            raise ValueError('Feedback graph mismatch')
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='feedback-replay-', dir=target.parent) as work:
            source = Path(work) / 'source'
            source_data = unpack_fragment_population(package, config.source_package_sha256,
                config.source_manifest_sha256, source, graph)
            source_config = FragmentPopulationConfig.model_validate(
                source_data['metadata']['configuration'])
            index = registered_index(Path(synapse_root), connectome_directory() / 'ids.npy')
            discretization_context = None
            from service.settings import feedback_cache_bytes

            loop_options = {'experimental_cache_bytes': feedback_cache_bytes()}
            if config.discretization is not None:
                policy = {'expected_source_md5': SOURCE_MD5,
                          **config.discretization.model_dump(mode='json')}
                discretization_context = {'index': index, 'directories': morphology_directories(),
                                          'policy': policy}
                loop_options['discretization_policy'] = policy
            result = iterate_population_feedback(source, graph, index, morphology_directories(),
                parameters=config.parameters(), max_iterations=config.max_iterations,
                allow_partial_geometry=config.allow_partial_geometry,
                stage_progress=lambda value: _write_progress(target.parent, value), **loop_options)
            if result.get('status') in ('iteration_limit', 'cycle_detected'):
                fields = ('iteration', 'input_events', 'unresolved_events', 'outside_window',
                          'output_edge_records', 'network_spikes')
                history = result.get('iterations')
                if (not isinstance(history, list) or not 1 <= len(history) <= config.max_iterations
                        or any(not isinstance(row, dict) or any(type(row.get(key)) is not int
                            or not 0 <= row[key] <= 1_000_000_000 for key in fields)
                            or row['iteration'] != position
                            for position, row in enumerate(history, 1))):
                    raise ValueError('Invalid feedback diagnostic history')
                feedback_diagnostics = {'status': result['status'],
                                        'history': [{key: row[key] for key in fields}
                                                    for row in history]}
                raise ValueError(f"Coupled feedback did not converge: {result['status']}")
            target.mkdir(parents=True, exist_ok=False)
            archive_path = target / 'coupled-population.zip'
            archive_hash = write_population_feedback(result, archive_path, source_directory=source,
                graph=graph, parameters=config.parameters(),
                allow_partial_geometry=config.allow_partial_geometry,
                discretization_context=discretization_context)
            checked = read_population_feedback(archive_path, source_directory=source, graph=graph,
                parameters=config.parameters(),
                allow_partial_geometry=config.allow_partial_geometry,
                discretization_context=discretization_context)
            preview = population_feedback_preview(checked, graph, source_config)
            preview_path = target / 'coupled-preview.json'
            write_json(preview_path, preview)
            delta_path = target / 'coupled-delta.bin'
            delta_path.write_bytes(encode_sparse_delta(checked['network']['sparse_delta'],
                graph=graph, source_ids=source_config.source_ids,
                duration_ms=int(source_config.simulation.duration_ms),
                configuration_sha256=config.digest()))
            event_data, _, event_hash = encode_forced_spikes(graph, checked['network'])
            event_path = target / 'coupled-events.bin'
            event_path.write_bytes(event_data)
            source_event_path = target / 'coupled-source-events.bin'
            source_event_path.write_bytes(encode_population_source_events(
                checked['physical_source_output'], graph,
                duration_ms=int(source_config.simulation.duration_ms),
                configuration_sha256=config.digest()))
            rows = [{'name': archive_path.name, 'bytes': archive_path.stat().st_size,
                     'sha256': archive_hash},
                    {'name': preview_path.name, 'bytes': preview_path.stat().st_size,
                     'sha256': hashlib.sha256(preview_path.read_bytes()).hexdigest()},
                    {'name': delta_path.name, 'bytes': delta_path.stat().st_size,
                     'sha256': hashlib.sha256(delta_path.read_bytes()).hexdigest()},
                    {'name': event_path.name, 'bytes': event_path.stat().st_size,
                     'sha256': event_hash},
                    {'name': source_event_path.name, 'bytes': source_event_path.stat().st_size,
                     'sha256': hashlib.sha256(source_event_path.read_bytes()).hexdigest()}]
            write_json(target / 'manifest.json', {'kind': 'experimental-coupled-population',
                'configuration_sha256': config.digest(),
                'graph_sha256': source_config.graph_manifest_sha256,
                'source_package_sha256': config.source_package_sha256,
                'source_manifest_sha256': config.source_manifest_sha256, 'files': rows})
    except Exception as exc:
        target.mkdir(parents=True, exist_ok=True)
        error = {'type': type(exc).__name__, 'message': str(exc)[:1000]}
        if feedback_diagnostics is not None:
            error['feedback_diagnostics'] = feedback_diagnostics
        write_json(target / 'error.json', error)
        raise


def run_population_target_child(payload: dict, directory: str, input_root: str) -> None:
    """Restore an authenticated package in a private temporary workspace and replay it."""
    import tempfile

    from service.application.replay.verified_population_target import (
        replay_verified_population_target,
    )
    from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
    from service.domain.contracts.population_target_contract import PopulationTargetExecutionRequest
    from service.infrastructure.connectome.neighbors import registered_graph
    from service.infrastructure.connectome.synapse_repository import registered_index
    from service.infrastructure.stimulation.fragment_population_transport import (
        unpack_fragment_population,
    )
    from service.infrastructure.stimulation.verified_target_archive import (
        read_target_replay,
        write_target_replay,
    )
    from service.settings import connectome_directory, morphology_directories

    target = Path(directory)
    try:
        request = PopulationTargetExecutionRequest.model_validate(payload)
        config = request.config
        package = ReplayInputStore(Path(input_root)).path(request.execution_id)
        synapse_root = os.environ.get('GENERATOR_SYNAPSE_DIR', '')
        if not synapse_root:
            raise ValueError('Synapse source is not configured')
        graph = registered_graph()
        if graph.provenance.get('manifest_sha256') != config.graph_manifest_sha256:
            raise ValueError('Target graph mismatch')
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='target-replay-', dir=target.parent) as work:
            restored = Path(work) / 'source'
            checked = unpack_fragment_population(package, config.source_package_sha256,
                config.source_manifest_sha256, restored, graph)
            source_config = FragmentPopulationConfig.model_validate(
                checked['metadata']['configuration'])
            if source_config.simulation.duration_ms != config.duration_ms:
                raise ValueError('Target duration differs from the source run')
            index = registered_index(Path(synapse_root), connectome_directory() / 'ids.npy')
            result = replay_verified_population_target(restored, graph, index,
                morphology_directories(), target_id=config.target_id, source_ids=config.source_ids,
                schedule_parameters=config.schedules(),
                max_target_distance_um=config.max_target_distance_um, max_events=config.max_events,
                timing_mode=config.timing_mode or 'tick')
            write_target_replay(result, target, execution_provenance={
                'configuration_sha256': config.digest(),
                'source_package_sha256': config.source_package_sha256,
                'source_manifest_sha256': config.source_manifest_sha256,
            })
            read_target_replay(target)
    except Exception as exc:
        target.mkdir(parents=True, exist_ok=True)
        write_json(target / 'error.json', {'type': type(exc).__name__, 'message': str(exc)[:1000]})
        raise


class Executions:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.processes: dict[str, mp.Process] = {}

    def receipt(self, execution_id: str) -> Path:
        return self.root / execution_id / "receipt.json"

    def save(self, record: dict) -> None:
        path = self.receipt(record["execution_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        write_json(temporary, record)
        temporary.replace(path)

    def status(self, execution_id: str) -> dict:
        with self.lock:
            path = self.receipt(execution_id)
            if not path.is_file():
                raise KeyError(execution_id)
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["status"] == "running":
                process = self.processes.get(execution_id)
                if process is None or not process.is_alive():
                    if process:
                        process.join(timeout=1)
                    output = path.parent / "output"
                    manifest = output / "manifest.json"
                    if manifest.exists() and process is not None and process.exitcode == 0:
                        record.update(status="completed", manifest=json.loads(manifest.read_text()))
                    elif process is None:
                        record.update(status="interrupted", error="Executor restarted")
                    else:
                        error = output / "error.json"
                        record.update(
                            status="failed",
                            error=(
                                json.loads(error.read_text())
                                if error.exists()
                                else {"message": f"Solver exit {process.exitcode}"}
                            ),
                        )
                    record["finished_at"] = time()
                    self.save(record)
                elif (path.parent / 'progress.json').is_file():
                    try:
                        progress = json.loads((path.parent / 'progress.json').read_text('utf8'))
                        if _valid_progress(progress):
                            record['progress'] = progress
                    except (OSError, ValueError):
                        pass
            return record

    def start(self, request: ExecutionRequest) -> dict:
        with self.lock:
            if self.receipt(request.execution_id).exists():
                previous = self.status(request.execution_id)
                if (previous.get("kind", "simulation") != "simulation"
                        or previous["configuration_sha256"] != request.config.digest()):
                    raise ValueError("Execution ID already belongs to another configuration")
                return previous
            for execution_id in list(self.processes):
                if self.status(execution_id)["status"] == "running":
                    raise RuntimeError("Executor busy")
            output = self.root / request.execution_id / "output"
            record = {
                "execution_id": request.execution_id,
                "status": "running",
                "configuration_sha256": request.config.digest(),
                "started_at": time(),
                "acknowledged": False,
            }
            process = mp.get_context("spawn").Process(
                target=run_child,
                args=(request.config.model_dump(), str(output)),
                daemon=True,
            )
            self.save(record)
            try:
                process.start()
            except Exception:
                record.update(status="failed", error="Could not start solver")
                self.save(record)
                raise
            self.processes[request.execution_id] = process
            return record

    def start_replay(self, request: ReplayExecutionRequest) -> dict:
        execution_id = str(request.execution_id)
        try:
            encoded = json.dumps(request.source_description, sort_keys=True, allow_nan=False,
                                 separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid replay source description") from exc
        description_sha256 = hashlib.sha256(encoded).hexdigest()
        with self.lock:
            if self.receipt(execution_id).exists():
                previous = self.status(execution_id)
                if (previous.get("kind") != "replay"
                        or previous["configuration_sha256"] != request.config.digest()
                        or previous.get("source_sha256") != request.source_sha256
                        or previous.get("description_sha256") != description_sha256):
                    raise ValueError("Execution ID already belongs to another configuration")
                return previous
            for active in list(self.processes):
                if self.status(active)["status"] == "running":
                    raise RuntimeError("Executor busy")
            source = ReplayInputStore(self.root).path(request.execution_id)
            if not source.is_file() or ReplayInputStore._digest(source) != request.source_sha256:
                raise ValueError("Replay input missing or checksum mismatch")
            output = self.root / execution_id / "output"
            record = {"execution_id": execution_id, "kind": "replay", "status": "running",
                      "configuration_sha256": request.config.digest(),
                      "source_sha256": request.source_sha256,
                      "description_sha256": description_sha256,
                      "started_at": time(), "acknowledged": False}
            process = mp.get_context("spawn").Process(
                target=run_replay_child,
                args=(request.model_dump(mode="json"), str(output), str(self.root)),
                daemon=True,
            )
            self.save(record)
            try:
                process.start()
            except Exception:
                record.update(status="failed", error="Could not start solver")
                self.save(record)
                raise
            self.processes[execution_id] = process
            return record

    def start_field_graph(self, request: FieldGraphExecutionRequest) -> dict:
        execution_id = str(request.execution_id)
        with self.lock:
            if self.receipt(execution_id).exists():
                previous = self.status(execution_id)
                if (previous.get("kind") != "field-graph-replay"
                        or previous["configuration_sha256"] != request.config.digest()):
                    raise ValueError("Execution ID already belongs to another configuration")
                return previous
            for active in list(self.processes):
                if self.status(active)["status"] == "running":
                    raise RuntimeError("Executor busy")
            output = self.root / execution_id / "output"
            record = {"execution_id": execution_id, "kind": "field-graph-replay",
                      "status": "running",
                      "configuration_sha256": request.config.digest(), "started_at": time(),
                      "acknowledged": False}
            process = mp.get_context("spawn").Process(
                target=run_field_graph_child, args=(request.model_dump(mode="json"), str(output)),
                daemon=True,
            )
            self.save(record)
            try:
                process.start()
            except Exception:
                record.update(status="failed", error="Could not start solver")
                self.save(record)
                raise
            self.processes[execution_id] = process
            return record

    def start_field_proxy(self, request: FieldProxyExecutionRequest) -> dict:
        execution_id = str(request.execution_id)
        with self.lock:
            if self.receipt(execution_id).exists():
                previous = self.status(execution_id)
                if (previous.get('kind') != 'experimental-field-proxy'
                        or previous['configuration_sha256'] != request.config.digest()):
                    raise ValueError('Execution ID already belongs to another configuration')
                return previous
            for active in list(self.processes):
                if self.status(active)['status'] == 'running':
                    raise RuntimeError('Executor busy')
            output = self.root / execution_id / 'output'
            record = {'execution_id': execution_id, 'kind': 'experimental-field-proxy',
                      'status': 'running', 'configuration_sha256': request.config.digest(),
                      'started_at': time(), 'acknowledged': False}
            grouped = os.name == 'posix'
            process = mp.get_context('spawn').Process(
                target=run_field_proxy_group if grouped else run_field_proxy_child,
                args=(request.model_dump(mode='json'), str(output)), daemon=not grouped)
            self.save(record)
            try:
                process.start()
            except Exception:
                record.update(status='failed', error='Could not start solver')
                self.save(record)
                raise
            self.processes[execution_id] = process
            return record

    def start_fragment_population(self, request: FragmentPopulationExecutionRequest) -> dict:
        execution_id = str(request.execution_id)
        with self.lock:
            if self.receipt(execution_id).exists():
                previous = self.status(execution_id)
                if (previous.get('kind') != 'experimental-fragment-population'
                        or previous['configuration_sha256'] != request.config.digest()):
                    raise ValueError('Execution ID already belongs to another configuration')
                return previous
            for active in list(self.processes):
                if self.status(active)['status'] == 'running':
                    raise RuntimeError('Executor busy')
            output = self.root / execution_id / 'output'
            record = {'execution_id': execution_id, 'kind': 'experimental-fragment-population',
                      'status': 'running', 'configuration_sha256': request.config.digest(),
                      'started_at': time(), 'acknowledged': False}
            process = mp.get_context('spawn').Process(
                target=run_fragment_population_child,
                args=(request.model_dump(mode='json'), str(output)), daemon=True)
            self.save(record)
            try:
                process.start()
            except Exception:
                record.update(status='failed', error='Could not start solver')
                self.save(record)
                raise
            self.processes[execution_id] = process
            return record

    def start_population_feedback(self, request: PopulationFeedbackExecutionRequest) -> dict:
        execution_id = str(request.execution_id)
        with self.lock:
            if self.receipt(execution_id).exists():
                previous = self.status(execution_id)
                if (previous.get('kind') != 'experimental-coupled-population'
                        or previous['configuration_sha256'] != request.config.digest()):
                    raise ValueError('Execution ID already belongs to another configuration')
                return previous
            for active in list(self.processes):
                if self.status(active)['status'] == 'running':
                    raise RuntimeError('Executor busy')
            source = ReplayInputStore(self.root).path(request.execution_id)
            if (not source.is_file() or source.is_symlink()
                    or ReplayInputStore._digest(source) != request.config.source_package_sha256):
                raise ValueError('Feedback input missing or checksum mismatch')
            output = self.root / execution_id / 'output'
            record = {'execution_id': execution_id, 'kind': 'experimental-coupled-population',
                      'status': 'running', 'configuration_sha256': request.config.digest(),
                      'source_sha256': request.config.source_package_sha256,
                      'started_at': time(), 'acknowledged': False}
            process = mp.get_context('spawn').Process(
                target=run_population_feedback_child,
                args=(request.model_dump(mode='json'), str(output), str(self.root)), daemon=True)
            self.save(record)
            try:
                process.start()
            except Exception:
                record.update(status='failed', error='Could not start solver')
                self.save(record)
                raise
            self.processes[execution_id] = process
            return record

    def start_population_target(self, request: PopulationTargetExecutionRequest) -> dict:
        execution_id = str(request.execution_id)
        with self.lock:
            if self.receipt(execution_id).exists():
                previous = self.status(execution_id)
                if (previous.get('kind') != 'experimental-one-way-target-replay'
                        or previous['configuration_sha256'] != request.config.digest()):
                    raise ValueError('Execution ID already belongs to another configuration')
                return previous
            for active in list(self.processes):
                if self.status(active)['status'] == 'running':
                    raise RuntimeError('Executor busy')
            source = ReplayInputStore(self.root).path(request.execution_id)
            if (not source.is_file() or source.is_symlink()
                    or ReplayInputStore._digest(source) != request.config.source_package_sha256):
                raise ValueError('Target input missing or checksum mismatch')
            output = self.root / execution_id / 'output'
            record = {'execution_id': execution_id, 'kind': 'experimental-one-way-target-replay',
                      'status': 'running', 'configuration_sha256': request.config.digest(),
                      'source_sha256': request.config.source_package_sha256,
                      'started_at': time(), 'acknowledged': False}
            process = mp.get_context('spawn').Process(
                target=run_population_target_child,
                args=(request.model_dump(mode='json'), str(output), str(self.root)), daemon=True)
            self.save(record)
            try:
                process.start()
            except Exception:
                record.update(status='failed', error='Could not start solver')
                self.save(record)
                raise
            self.processes[execution_id] = process
            return record

    def cancel(self, execution_id: str) -> dict:
        with self.lock:
            record = self.status(execution_id)
            if record["status"] == "running":
                process = self.processes.get(execution_id)
                if process and process.is_alive():
                    grouped = False
                    if (os.name == 'posix' and record.get('kind') == 'experimental-field-proxy'
                            and process.pid is not None):
                        try:
                            grouped = os.getpgid(process.pid) == process.pid
                            if grouped:
                                os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    if not grouped and process.is_alive():
                        process.terminate()
                    process.join(timeout=5)
                    if grouped:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    elif process.is_alive():
                        process.kill()
                    # Reap even when kill completed before the next is_alive().
                    process.join(timeout=5)
                    if process.is_alive():
                        # Keep the receipt running and leave working files intact:
                        # neither cancellation nor cleanup has been confirmed.
                        raise RuntimeError("Solver did not stop; cancellation is not confirmed")
                record.update(status="cancelled", finished_at=time())
                work = self.receipt(execution_id).parent / "current-archive-work"
                if work.exists():
                    shutil.rmtree(work)
                if record.get('kind') == 'experimental-field-proxy':
                    work = self.receipt(execution_id).parent / 'field-proxy-work'
                    if work.is_dir() and not work.is_symlink():
                        shutil.rmtree(work)
                if record.get('kind') == 'experimental-one-way-target-replay':
                    for work in self.receipt(execution_id).parent.glob('target-replay-*'):
                        if work.is_dir() and not work.is_symlink():
                            shutil.rmtree(work)
                if record.get('kind') == 'experimental-coupled-population':
                    for work in self.receipt(execution_id).parent.glob('feedback-replay-*'):
                        if work.is_dir() and not work.is_symlink():
                            shutil.rmtree(work)
                self.save(record)
            return record

    def acknowledge(self, execution_id: str, configuration_sha256: str) -> dict:
        with self.lock:
            record = self.status(execution_id)
            if (
                record["status"] != "completed"
                or record["configuration_sha256"] != configuration_sha256
            ):
                raise ValueError("Only the verified completed configuration can be acknowledged")
            # root and execution id are service-owned; never accept caller filesystem paths.
            output = self.receipt(execution_id).parent / "output"
            if output.exists():
                shutil.rmtree(output)
            if record.get("kind") in {"replay", "experimental-one-way-target-replay",
                                      "experimental-coupled-population"}:
                ReplayInputStore(self.root).discard(UUID(execution_id), record["source_sha256"])
            record["acknowledged"] = True
            self.save(record)
            return record

    def discard(self, execution_id: str, configuration_sha256: str) -> dict:
        with self.lock:
            record = self.status(execution_id)
            if record["configuration_sha256"] != configuration_sha256 or record["acknowledged"]:
                raise ValueError("Cannot discard another or already published configuration")
            self.cancel(execution_id)
            output = self.receipt(execution_id).parent / "output"
            if output.exists():
                shutil.rmtree(output)
            if record.get("kind") in {"replay", "experimental-one-way-target-replay",
                                      "experimental-coupled-population"}:
                ReplayInputStore(self.root).discard(UUID(execution_id), record["source_sha256"])
            if record.get('kind') == 'experimental-one-way-target-replay':
                for work in self.receipt(execution_id).parent.glob('target-replay-*'):
                    if work.is_dir() and not work.is_symlink():
                        shutil.rmtree(work)
            if record.get('kind') == 'experimental-coupled-population':
                for work in self.receipt(execution_id).parent.glob('feedback-replay-*'):
                    if work.is_dir() and not work.is_symlink():
                        shutil.rmtree(work)
            record.update(status="cancelled", discarded=True, finished_at=time())
            self.save(record)
            return record

    def close(self) -> None:
        for execution_id in list(self.processes):
            with self.lock:
                previous = self.status(execution_id)
                if previous["status"] == "running":
                    record = self.cancel(execution_id)
                    record.update(status="interrupted", error="Executor shutdown")
                    self.save(record)
