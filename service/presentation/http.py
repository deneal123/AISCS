"""Private, authenticated executor HTTP contract; ownership remains in the platform backend."""

from __future__ import annotations

import asyncio
import hmac
import tempfile
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, ValidationError, model_validator

from service import __version__
from service.contracts import Contract, ExecutionRequest, Finite, SimulationConfig
from service.domain.catalog import catalog
from service.domain.contracts.field_graph_contract import (
    FieldGraphAcquisition,
    FieldGraphConfig,
    FieldGraphExecutionRequest,
)
from service.domain.contracts.field_proxy_contract import (
    FieldProxyConfig,
    FieldProxyExecutionRequest,
    from_fragment_population,
    from_simulation,
)
from service.domain.contracts.fragment_population_contract import (
    FragmentPopulationConfig,
    FragmentPopulationExecutionRequest,
)
from service.domain.geometry import local_geometry
from service.domain.placement import validate_contacts
from service.domain.contracts.population_feedback_contract import (
    PopulationFeedbackConfig,
    PopulationFeedbackExecutionRequest,
)
from service.domain.contracts.population_target_contract import (
    PopulationTargetConfig,
    PopulationTargetExecutionRequest,
)
from service.domain.contracts.replay_contract import ReplayExecutionRequest, ReplayRunConfig
from service.domain.contracts.replay_contract import ReplaySimulation
from service.domain.surface_anchors import validate_surface_anchors
from service.infrastructure.execution.process import Executions
from service.infrastructure.execution.replay_input import ReplayInputStore


class Ack(BaseModel):
    configuration_sha256: str


class NativeFieldRequest(Contract):
    source_um: tuple[Finite, Finite, Finite]
    return_um: tuple[Finite, Finite, Finite]
    current_na: Finite
    conductivity_s_m: Finite
    clearance_um: Finite

    @model_validator(mode="after")
    def positive_medium(self):
        if self.conductivity_s_m <= 0 or self.clearance_um <= 0:
            raise ValueError("Conductivity and clearance must be positive")
        return self


class SpatialCandidatesRequest(Contract):
    source_um: tuple[Finite, Finite, Finite]
    return_um: tuple[Finite, Finite, Finite]
    radius_um: Finite
    electrode_um: tuple[Finite, Finite, Finite] | None = None
    reference_um: tuple[Finite, Finite, Finite] | None = None

    @model_validator(mode="after")
    def valid_radius(self):
        if self.radius_um < 0 or (self.electrode_um is None) != (self.reference_um is None):
            raise ValueError("Radius must be nonnegative")
        return self


class ContactScreenRequest(Contract):
    source_um: tuple[Finite, Finite, Finite]
    return_um: tuple[Finite, Finite, Finite]
    electrode_um: tuple[Finite, Finite, Finite]
    reference_um: tuple[Finite, Finite, Finite]
    clearance_um: Finite

    @model_validator(mode="after")
    def positive_clearance(self):
        if self.clearance_um <= 0:
            raise ValueError("Clearance must be positive")
        return self


class FieldProxyFromFragmentRequest(Contract):
    population: FragmentPopulationConfig
    gain: Finite
    allow_partial_geometry: bool = Field(strict=True)
    allow_missing_curvature: bool = Field(strict=True)
    allow_contact_exclusion: bool = Field(strict=True)


class FieldProxyFromSimulationRequest(Contract):
    simulation: ReplaySimulation
    graph_manifest_sha256: str
    seed: int = Field(strict=True, ge=0, le=2**31 - 1)
    gain: Finite
    allow_partial_geometry: bool = Field(strict=True)
    allow_missing_curvature: bool = Field(strict=True)
    allow_contact_exclusion: bool = Field(strict=True)


class ContactPositionsRequest(Contract):
    positions_um: list[tuple[Finite, Finite, Finite]] = Field(min_length=1, max_length=64)
    clearance_um: Finite

    @model_validator(mode="after")
    def positive_clearance(self):
        if self.clearance_um <= 0:
            raise ValueError("Clearance must be positive")
        return self


class RerecordPreviewRequest(Contract):
    package_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    current_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    electrode_um: tuple[Finite, Finite, Finite]
    reference_um: tuple[Finite, Finite, Finite]
    source_model: Literal["pointsource", "linesource"]
    acquisition: FieldGraphAcquisition | None = None


def build_app(manager: Executions, secret: str, readiness, catalog_factory=catalog) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.close()

    app = FastAPI(title="Neural generator executor", version=__version__, lifespan=lifespan)
    spatial_search_slot = threading.BoundedSemaphore(1)
    rerecord_slot = asyncio.Semaphore(1)

    def authorize(authorization: str = Header(default="")):
        if not hmac.compare_digest(authorization, "Bearer " + secret):
            raise HTTPException(401, "Invalid service credential")

    def read(execution_id: UUID):
        try:
            return manager.status(str(execution_id))
        except KeyError as exc:
            raise HTTPException(404, "Execution not found") from exc

    protected = [Depends(authorize)]
    replay_inputs = ReplayInputStore(manager.root)

    @app.post("/v1/rerecord-preview", dependencies=protected)
    async def rerecord_preview_http(
        request: Request, x_recording_configuration: str = Header(alias="X-Recording-Configuration")
    ):
        from service.application.replay.rerecord_preview import rerecord_preview

        try:
            if len(x_recording_configuration) > 4096:
                raise ValueError("Configuration too large")
            config = RerecordPreviewRequest.model_validate_json(x_recording_configuration)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(422, "Invalid recording configuration") from exc
        if rerecord_slot.locked():
            raise HTTPException(429, "Recording executor busy")
        async with rerecord_slot:
            with tempfile.TemporaryDirectory(prefix="rerecord-http-", dir=manager.root) as temp:
                directory = Path(temp)
                package = directory / "input.zip"
                size = 0
                with package.open("xb") as stream:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 256 * 1024 * 1024:
                            raise HTTPException(413, "Recording archive too large")
                        stream.write(chunk)
                try:
                    operation = asyncio.create_task(asyncio.to_thread(
                        rerecord_preview, package, config.package_sha256,
                        config.current_manifest_sha256, directory / "work",
                        config.electrode_um, config.reference_um,
                        source_model=config.source_model,
                        acquisition=(config.acquisition.model_dump()
                                     if config.acquisition else None),
                    ))
                    try:
                        return await asyncio.shield(operation)
                    except asyncio.CancelledError:
                        while not operation.done():
                            try:
                                await asyncio.shield(operation)
                            except asyncio.CancelledError:
                                continue
                            except Exception:
                                break
                        if not operation.cancelled():
                            try:
                                operation.result()
                            except Exception:
                                pass
                        raise
                except (ValueError, OSError, zipfile.BadZipFile) as exc:
                    raise HTTPException(422, "Invalid recording archive or contacts") from exc

    def overview_path():
        import os

        path = os.environ.get("GENERATOR_CNS_OVERVIEW_DIR", "")
        if not path:
            raise HTTPException(503, "Overview is not configured")
        return Path(path)

    def neuropil_path():
        import os

        path = os.environ.get("GENERATOR_NEUROPIL_DIR", "")
        if not path:
            raise HTTPException(503, "Neuropil is not configured")
        return Path(path)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/ready", dependencies=protected)
    def ready():
        return readiness()

    @app.get("/capabilities", dependencies=protected)
    def capabilities():
        return catalog_factory()

    @app.get("/v1/connectome/overview", dependencies=protected)
    def cns_overview():
        from service.infrastructure.connectome.overview_repository import overview_manifest

        try:
            return overview_manifest(overview_path())
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Verified CNS overview unavailable") from exc

    @app.get("/v1/connectome/overview/{name}", dependencies=protected)
    def cns_overview_chunk(name: str):
        from service.infrastructure.connectome.overview_repository import overview_chunk

        try:
            return Response(overview_chunk(overview_path(), name), media_type="application/gzip")
        except FileNotFoundError as exc:
            raise HTTPException(404, "Overview chunk unavailable") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Verified CNS overview unavailable") from exc

    @app.get("/v1/connectome/neuropil", dependencies=protected)
    def neuropil():
        from service.infrastructure.connectome.neuropil_repository import neuropil_manifest

        try:
            return neuropil_manifest(neuropil_path())
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Verified neuropil unavailable") from exc

    @app.get("/v1/connectome/neuropil/{name}", dependencies=protected)
    def neuropil_part(name: str):
        from service.infrastructure.connectome.neuropil_repository import neuropil_chunk

        try:
            return Response(neuropil_chunk(neuropil_path(), name), media_type="application/gzip")
        except FileNotFoundError as exc:
            raise HTTPException(404, "Neuropil mesh unavailable") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Verified neuropil unavailable") from exc

    @app.get("/v1/connectome/neurons/{body_id}/{direction}", dependencies=protected)
    def neuron_connections(
        body_id: str,
        direction: Literal["incoming", "outgoing"],
        offset: int = Query(default=0, ge=0, le=25_582_938),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        if (
            not body_id.isascii()
            or not body_id.isdigit()
            or body_id.startswith("0")
            or len(body_id) > 19
            or int(body_id) > 2**63 - 1
        ):
            raise HTTPException(422, "Invalid neuron ID")
        from service.infrastructure.connectome.neighbors import incoming, outgoing, registered_graph

        try:
            query = incoming if direction == "incoming" else outgoing
            return query(registered_graph(), int(body_id), offset, limit)
        except KeyError as exc:
            raise HTTPException(404, "Neuron not found") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Registered graph unavailable") from exc

    @app.get("/v1/connectome/neurons/{body_id}/{direction}/synapses", dependencies=protected)
    def neuron_synapses(
        body_id: str,
        direction: Literal["incoming", "outgoing"],
        offset: int = Query(default=0, ge=0, le=25_582_938),
        limit: int = Query(default=20, ge=1, le=20),
    ):
        import os

        from service.infrastructure.connectome.neighbors import registered_graph
        from service.infrastructure.connectome.synapse_index import registered_page_pairs
        from service.infrastructure.connectome.synapse_repository import registered_index
        from service.settings import connectome_directory

        if (not body_id.isascii() or not body_id.isdigit() or body_id.startswith("0")
                or len(body_id) > 19 or int(body_id) > 2**63 - 1):
            raise HTTPException(422, "Invalid neuron ID")
        root = os.environ.get("GENERATOR_SYNAPSE_DIR", "")
        if not root:
            raise HTTPException(503, "Synapse data not configured")
        try:
            graph = registered_graph()
            index = registered_index(Path(root), connectome_directory() / "ids.npy")
            result = registered_page_pairs(index, graph, int(body_id), direction, offset, limit)
            if not result["counts_match"]:
                raise HTTPException(409, "Synapse counts differ from registered graph")
            return result
        except KeyError as exc:
            raise HTTPException(404, "Neuron not found") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Verified synapse data unavailable") from exc

    @app.get("/v1/connectome/morphology/{body_id}", dependencies=protected)
    def neuron_morphology(body_id: str):
        if (not body_id.isascii() or not body_id.isdigit() or body_id.startswith("0")
                or len(body_id) > 19 or int(body_id) > 2**63 - 1):
            raise HTTPException(422, "Invalid neuron ID")
        import numpy as np

        from service.infrastructure.connectome.morphology_repository import read_skeleton
        from service.infrastructure.connectome.neighbors import registered_graph
        from service.settings import morphology_directories

        try:
            graph = registered_graph()
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Registered graph unavailable") from exc
        index = int(np.searchsorted(graph.ids, int(body_id)))
        if index >= len(graph.ids) or int(graph.ids[index]) != int(body_id):
            raise HTTPException(404, "Neuron not found")
        try:
            return {**read_skeleton(int(body_id), morphology_directories()),
                    "dataset_id": graph.provenance["dataset_id"],
                    "manifest_sha256": graph.provenance["manifest_sha256"]}
        except FileNotFoundError as exc:
            raise HTTPException(404, "Source skeleton not acquired") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Source skeleton unavailable or invalid") from exc

    @app.post("/v1/connectome/morphology/{body_id}/field", dependencies=protected)
    def neuron_native_field(body_id: str, request: NativeFieldRequest):
        from service.infrastructure.stimulation.morphology_field import evaluate_swc_field

        skeleton = neuron_morphology(body_id)
        try:
            field = evaluate_swc_field(
                skeleton["swc"], request.source_um, request.return_um, request.current_na,
                request.conductivity_s_m, clearance_um=request.clearance_um,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "body_id": body_id,
            "manifest_sha256": skeleton["manifest_sha256"],
            "source_sha256": skeleton["sha256"],
            "coordinate_frame": "male-cns-v1.0-native-um",
            "medium": "infinite-homogeneous-isotropic",
            "interpretation": "field-only; not excitation or tissue-calibrated",
            "configuration": request.model_dump(),
            "vertex_ids": field["vertex_ids"].tolist(),
            "potential_mv": field["potential_mv"].tolist(),
            "curvature_vertex_ids": field["curvature_vertex_ids"].tolist(),
            "curvature_mv_per_um2": field["curvature_mv_per_um2"].tolist(),
        }

    @app.post("/v1/connectome/spatial-candidates", dependencies=protected)
    def find_spatial_candidates(request: SpatialCandidatesRequest):
        import os
        import sqlite3

        from service.infrastructure.connectome.neighbors import registered_graph
        from service.infrastructure.stimulation.spatial_candidates import spatial_candidates
        from service.settings import morphology_directories

        path = os.environ.get("GENERATOR_MORPHOLOGY_BOUNDS_DB", "")
        audit_path = os.environ.get("GENERATOR_MORPHOLOGY_BOUNDS_AUDIT", "")
        segment_path = os.environ.get("GENERATOR_MORPHOLOGY_SEGMENT_DB", "")
        segment_audit = os.environ.get("GENERATOR_MORPHOLOGY_SEGMENT_AUDIT", "")
        if not path or not Path(path).is_file() or not audit_path or not Path(audit_path).is_file():
            raise HTTPException(503, "Verified morphology index is unavailable")
        if not spatial_search_slot.acquire(blocking=False):
            raise HTTPException(429, "Another spatial search is still running")
        try:
            graph = registered_graph()
            result = spatial_candidates(
                Path(path), graph.ids, graph.provenance["manifest_sha256"],
                morphology_directories(),
                [request.source_um, request.return_um], request.radius_um,
                audit_report=Path(audit_path),
                workers=int(os.environ.get("GENERATOR_MORPHOLOGY_SPATIAL_WORKERS", "1")),
                segment_index=Path(segment_path) if segment_path else None,
                segment_audit=Path(segment_audit) if segment_audit else None,
                recording_contacts=([request.electrode_um, request.reference_um]
                                    if request.electrode_um is not None else None),
            )
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise HTTPException(503, "Morphology index is incomplete or invalid") from exc
        finally:
            spatial_search_slot.release()
        return {**result, "manifest_sha256": graph.provenance["manifest_sha256"],
                "configuration": request.model_dump(mode="json")}

    def _contact_screen(request, *, positions: bool):
        import os
        import sqlite3

        from service.infrastructure.connectome.neighbors import registered_graph
        from service.infrastructure.stimulation.contact_screen import (
            screen_contact_positions,
            screen_contacts,
        )
        from service.settings import morphology_directories

        paths = [os.environ.get(key, "") for key in (
            "GENERATOR_MORPHOLOGY_BOUNDS_DB", "GENERATOR_MORPHOLOGY_BOUNDS_AUDIT",
            "GENERATOR_MORPHOLOGY_RADIUS_DB", "GENERATOR_MORPHOLOGY_RADIUS_AUDIT",
        )]
        segment_path = os.environ.get("GENERATOR_MORPHOLOGY_SEGMENT_DB", "")
        segment_audit = os.environ.get("GENERATOR_MORPHOLOGY_SEGMENT_AUDIT", "")
        if any(not path or not Path(path).is_file() for path in paths):
            raise HTTPException(503, "Verified contact-screen indexes are unavailable")
        if not spatial_search_slot.acquire(blocking=False):
            raise HTTPException(429, "Another spatial search is still running")
        try:
            graph = registered_graph()
            result = (screen_contact_positions if positions else screen_contacts)(
                *(Path(path) for path in paths), graph.ids, graph.provenance["manifest_sha256"],
                morphology_directories(),
                (request.positions_um if positions else [
                    request.source_um, request.return_um,
                    request.electrode_um, request.reference_um,
                ]),
                request.clearance_um,
                segment_index=Path(segment_path) if segment_path else None,
                segment_audit=Path(segment_audit) if segment_audit else None,
                workers=int(os.environ.get("GENERATOR_MORPHOLOGY_SPATIAL_WORKERS", "1")),
            )
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise HTTPException(503, "Contact-screen index is incomplete or invalid") from exc
        finally:
            spatial_search_slot.release()
        return {**result, "manifest_sha256": graph.provenance["manifest_sha256"],
                "configuration": request.model_dump(mode="json")}

    @app.post("/v1/connectome/contact-screen", dependencies=protected)
    def contact_screen(request: ContactScreenRequest):
        return _contact_screen(request, positions=False)

    @app.post("/v1/connectome/contact-positions", dependencies=protected)
    def contact_positions(request: ContactPositionsRequest):
        return _contact_screen(request, positions=True)

    @app.post("/v1/validate", dependencies=protected)
    def validate(config: SimulationConfig):
        import numpy as np

        geometry = local_geometry()
        if config.model_id == "male-cns-hybrid-v1":
            from service.settings import connectome_directory

            if not (connectome_directory() / "manifest.json").is_file():
                raise HTTPException(503, "Registered MaleCNS data are not installed")
        try:
            validate_surface_anchors(config)
            validate_contacts(
                config,
                np.array(geometry["starts_um"]),
                np.array(geometry["ends_um"]),
                np.array(geometry["diameters_um"]),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"configuration": config.model_dump(), "configuration_sha256": config.digest()}

    @app.post("/v1/replay-validate", dependencies=protected)
    def validate_replay(config: ReplayRunConfig):
        import numpy as np

        from service.infrastructure.connectome.neighbors import registered_graph

        try:
            graph = registered_graph()
            if graph.provenance.get("manifest_sha256") != config.graph_manifest_sha256:
                raise HTTPException(409, "Replay graph does not match installed graph")
            index = int(np.searchsorted(graph.ids, config.body_id))
            if index >= len(graph.ids) or int(graph.ids[index]) != config.body_id:
                raise HTTPException(404, "Replay neuron not found")
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Registered graph unavailable") from exc
        return {"configuration": config.model_dump(mode="json"),
                "configuration_sha256": config.digest()}

    @app.post("/v1/field-graph-validate", dependencies=protected)
    def validate_field_graph(config: FieldGraphConfig):
        import numpy as np

        from service.infrastructure.connectome.neighbors import registered_graph

        try:
            graph = registered_graph()
            if graph.provenance.get("manifest_sha256") != config.graph_manifest_sha256:
                raise HTTPException(409, "Field graph does not match installed graph")
            ids = [cell.body_id for cell in config.source_cells] + config.replay_ids
            positions = np.searchsorted(graph.ids, ids)
            if any(pos >= len(graph.ids) or int(graph.ids[pos]) != body
                   for pos, body in zip(positions, ids, strict=True)):
                raise HTTPException(404, "Field graph neuron not found")
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Registered graph unavailable") from exc
        return {"configuration": config.model_dump(mode="json"),
                "configuration_sha256": config.digest()}

    @app.post('/v1/field-proxy-validate', dependencies=protected)
    def validate_field_proxy(config: FieldProxyConfig):
        from service.infrastructure.connectome.neighbors import registered_graph

        try:
            graph = registered_graph()
            if graph.provenance.get('manifest_sha256') != config.graph_manifest_sha256:
                raise HTTPException(409, 'Field graph does not match installed graph')
        except (OSError, ValueError) as exc:
            raise HTTPException(503, 'Registered graph unavailable') from exc
        return {'configuration': config.model_dump(mode='json'),
                'configuration_sha256': config.digest()}

    @app.post('/v1/field-proxy-from-fragment', dependencies=protected)
    def field_proxy_from_fragment(request: FieldProxyFromFragmentRequest):
        try:
            config = from_fragment_population(request.population, gain=request.gain,
                allow_partial_geometry=request.allow_partial_geometry,
                allow_missing_curvature=request.allow_missing_curvature,
                allow_contact_exclusion=request.allow_contact_exclusion)
        except ValueError as exc:
            raise HTTPException(422, 'Cannot derive a compatible field stimulus') from exc
        return validate_field_proxy(config)

    @app.post('/v1/field-proxy-from-simulation', dependencies=protected)
    def field_proxy_from_simulation(request: FieldProxyFromSimulationRequest):
        try:
            config = from_simulation(request.simulation,
                graph_manifest_sha256=request.graph_manifest_sha256, seed=request.seed,
                gain=request.gain, allow_partial_geometry=request.allow_partial_geometry,
                allow_missing_curvature=request.allow_missing_curvature,
                allow_contact_exclusion=request.allow_contact_exclusion)
        except ValueError as exc:
            raise HTTPException(422, 'Cannot derive a compatible field stimulus') from exc
        return validate_field_proxy(config)

    @app.post('/v1/fragment-population-validate', dependencies=protected)
    def validate_fragment_population(config: FragmentPopulationConfig):
        import numpy as np

        from service.infrastructure.connectome.neighbors import registered_graph

        try:
            graph = registered_graph()
            if graph.provenance.get('manifest_sha256') != config.graph_manifest_sha256:
                raise HTTPException(409, 'Fragment graph does not match installed graph')
            positions = np.searchsorted(graph.ids, config.source_ids)
            if any(pos >= len(graph.ids) or int(graph.ids[pos]) != body
                   for pos, body in zip(positions, config.source_ids, strict=True)):
                raise HTTPException(404, 'Fragment source neuron not found')
        except (OSError, ValueError) as exc:
            raise HTTPException(503, 'Registered graph unavailable') from exc
        return {'configuration': config.model_dump(mode='json'),
                'configuration_sha256': config.digest()}

    @app.post('/v1/population-feedback-validate', dependencies=protected)
    def validate_population_feedback(config: PopulationFeedbackConfig):
        from service.infrastructure.connectome.neighbors import registered_graph

        try:
            graph = registered_graph()
            if graph.provenance.get('manifest_sha256') != config.graph_manifest_sha256:
                raise HTTPException(409, 'Feedback graph does not match installed graph')
        except (OSError, ValueError) as exc:
            raise HTTPException(503, 'Registered graph unavailable') from exc
        return {'configuration': config.model_dump(mode='json'),
                'configuration_sha256': config.digest()}

    @app.post('/v1/population-target-validate', dependencies=protected)
    def validate_population_target(config: PopulationTargetConfig):
        import numpy as np

        from service.infrastructure.connectome.neighbors import registered_graph

        try:
            graph = registered_graph()
            if graph.provenance.get('manifest_sha256') != config.graph_manifest_sha256:
                raise HTTPException(409, 'Target graph does not match installed graph')
            ids = [*config.source_ids, config.target_id]
            positions = np.searchsorted(graph.ids, ids)
            if any(pos >= len(graph.ids) or int(graph.ids[pos]) != body
                   for pos, body in zip(positions, ids, strict=True)):
                raise HTTPException(404, 'Target or source neuron not found')
        except (OSError, ValueError) as exc:
            raise HTTPException(503, 'Registered graph unavailable') from exc
        return {'configuration': config.model_dump(mode='json'),
                'configuration_sha256': config.digest()}

    @app.put("/v1/replay-inputs/{execution_id}", dependencies=protected)
    async def upload_replay_input(
        execution_id: UUID, request: Request,
        x_content_sha256: str = Header(alias="X-Content-SHA256"),
    ):
        try:
            return await replay_inputs.put(execution_id, x_content_sha256, request.stream())
        except ValueError as exc:
            status = 409 if "already has a different" in str(exc) else 422
            raise HTTPException(status, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Replay input storage unavailable") from exc

    @app.delete("/v1/replay-inputs/{execution_id}", dependencies=protected)
    def delete_replay_input(
        execution_id: UUID, x_content_sha256: str = Header(alias="X-Content-SHA256"),
    ):
        try:
            with manager.lock:
                try:
                    record = manager.status(str(execution_id))
                except KeyError:
                    record = None
                if record and record["status"] == "running":
                    raise HTTPException(409, "Replay execution is running")
                removed = replay_inputs.discard(execution_id, x_content_sha256)
            return {"removed": removed}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Replay input storage unavailable") from exc

    @app.post("/v1/executions", dependencies=protected)
    def start(request: ExecutionRequest):
        try:
            UUID(request.execution_id)
            return manager.start(request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/v1/replay-executions", dependencies=protected)
    def start_replay(request: ReplayExecutionRequest):
        try:
            return manager.start_replay(request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/v1/field-graph-executions", dependencies=protected)
    def start_field_graph(request: FieldGraphExecutionRequest):
        try:
            return manager.start_field_graph(request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post('/v1/field-proxy-executions', dependencies=protected)
    def start_field_proxy(request: FieldProxyExecutionRequest):
        try:
            return manager.start_field_proxy(request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post('/v1/fragment-population-executions', dependencies=protected)
    def start_fragment_population(request: FragmentPopulationExecutionRequest):
        try:
            return manager.start_fragment_population(request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post('/v1/population-feedback-executions', dependencies=protected)
    def start_population_feedback(request: PopulationFeedbackExecutionRequest):
        try:
            return manager.start_population_feedback(request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post('/v1/population-target-executions', dependencies=protected)
    def start_population_target(request: PopulationTargetExecutionRequest):
        try:
            return manager.start_population_target(request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/v1/executions/{execution_id}", dependencies=protected)
    def status(execution_id: UUID):
        return read(execution_id)

    @app.post("/v1/executions/{execution_id}/cancel", dependencies=protected)
    def cancel(execution_id: UUID):
        read(execution_id)
        return manager.cancel(str(execution_id))

    @app.get("/v1/executions/{execution_id}/manifest", dependencies=protected)
    def manifest(execution_id: UUID):
        record = read(execution_id)
        if record["status"] != "completed":
            raise HTTPException(409, "Execution not completed")
        return record["manifest"]

    @app.get("/v1/executions/{execution_id}/artifacts/{name}", dependencies=protected)
    def artifact(execution_id: UUID, name: str):
        record = read(execution_id)
        if record["status"] != "completed" or record["acknowledged"]:
            raise HTTPException(409, "Artifacts unavailable")
        allowed = {item["name"] for item in record["manifest"]["files"]} | {"manifest.json"}
        if name not in allowed or Path(name).name != name:
            raise HTTPException(404, "Artifact not found")
        return FileResponse(
            manager.receipt(str(execution_id)).parent / "output" / name, filename=name
        )

    @app.post("/v1/executions/{execution_id}/ack", dependencies=protected)
    def ack(execution_id: UUID, payload: Ack):
        read(execution_id)
        try:
            return manager.acknowledge(str(execution_id), payload.configuration_sha256)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/v1/executions/{execution_id}/discard", dependencies=protected)
    def discard(execution_id: UUID, payload: Ack):
        read(execution_id)
        try:
            return manager.discard(str(execution_id), payload.configuration_sha256)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    return app
