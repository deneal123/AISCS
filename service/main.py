"""Composition root. Each sidecar owns its Python environment and service package."""

from pathlib import Path

from service.application.generation import GenerateSignal
from service.infrastructure.artifacts.exporter import ArtifactWriter
from service.infrastructure.lfpy.recording import LFPyRecorder
from service.infrastructure.neuron.solver import NeuronEngine
from service.settings import Settings


def build_catalog() -> dict:
    from service.domain.catalog import catalog
    from service.settings import connectome_directory

    return catalog(connectome_available=(connectome_directory() / "manifest.json").is_file())


def build_generation() -> GenerateSignal:
    import os

    from service.infrastructure.connectome.engine import RegisteredEngine
    from service.infrastructure.execution.dynamics_cache import CachedDynamics

    engine = RegisteredEngine()
    runtime = Path(os.environ.get("GENERATOR_WORK_DIR", ".work/runtime"))
    cache = CachedDynamics(
        engine,
        runtime / "cache/dynamics",
        engine.identity(),
        max_bytes=int(os.environ.get("GENERATOR_CACHE_MAX_BYTES", str(128 * 1024 * 1024))),
    )
    return GenerateSignal(cache, ArtifactWriter())


def build_evaluation(directory: Path) -> dict:
    from service.application.evaluation import evaluate_classifier

    return evaluate_classifier(directory, NeuronEngine(), LFPyRecorder())


def build_connectome_evaluation(directory: Path, protocol: Path, phase: str) -> dict:
    from service.application.connectome_evaluation import evaluate_connectome
    from service.infrastructure.connectome.engine import RecordingEvaluationEngine
    from service.infrastructure.recognition.connectome_identity import numerical_identity

    return evaluate_connectome(
        directory,
        protocol,
        phase,
        RecordingEvaluationEngine(),
        LFPyRecorder(),
        numerical_identity(),
    )


def readiness() -> dict:
    import importlib.metadata

    from LFPy import RecExtElectrode
    from neuron import h

    return {
        "status": "ready",
        "neuron": h.nrnversion(),
        "lfpy": importlib.metadata.version("LFPy"),
        "operator": RecExtElectrode.__name__,
    }


def create_app(work_dir: Path | None = None, token: str | None = None):
    from service.infrastructure.execution.process import Executions
    from service.presentation.http import build_app

    settings = Settings.load(token=token, work_dir=work_dir)
    return build_app(Executions(settings.work_dir), settings.token, readiness, build_catalog)
