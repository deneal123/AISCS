import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    token: str = field(repr=False)
    work_dir: Path

    @classmethod
    def load(cls, *, token: str | None = None, work_dir: Path | None = None):
        secret = token if token is not None else os.environ.get("GENERATOR_TOKEN", "")
        if len(secret) < 24:
            raise RuntimeError("GENERATOR_TOKEN must contain at least 24 characters")
        return cls(secret, work_dir or Path(os.environ.get("GENERATOR_WORK_DIR", "/work")))


def model_path() -> Path:
    bundled = Path(__file__).resolve().parents[2] / "validation/demo-v1/classifier.json"
    if not bundled.is_file():
        bundled = (
            Path(__file__).resolve().parents[1] / "_bundled/validation/demo-v1/classifier.json"
        )
    return Path(os.environ.get("GENERATOR_MODEL_PATH", str(bundled)))


def connectome_directory() -> Path:
    default = Path(os.environ.get("GENERATOR_WORK_DIR", "/work")) / "datasets/malecns-v1/graph"
    return Path(os.environ.get("GENERATOR_CONNECTOME_DIR", str(default)))


def morphology_directories() -> list[Path]:
    value = os.environ.get("GENERATOR_MORPHOLOGY_DIRS", "")
    return [Path(item) for item in value.split(os.pathsep) if item]


def feedback_cache_bytes() -> int:
    """Default to a modest run-local cache; zero explicitly disables it."""
    value = os.environ.get('GENERATOR_FEEDBACK_CACHE_BYTES', '67108864')
    if not value.isascii() or not value.isdecimal():
        raise ValueError('GENERATOR_FEEDBACK_CACHE_BYTES must be a nonnegative integer')
    return int(value)


def source_diagnostics_cache_path() -> Path | None:
    """Durable cross-run cache of source cable mapping; unset keeps it run-local.

    The store keys every row by the authenticated dataset identity, so one file
    may serve several graphs, indexes and distance tolerances.
    """
    value = os.environ.get('GENERATOR_SOURCE_DIAGNOSTICS_CACHE', '')
    return Path(value) if value else None


def source_pair_directory() -> Path | None:
    """Optional authenticated grouped synapse-pair store. Unset keeps the packed scan.

    The store is a single sequential pass over the same synapse source, grouped by
    presynaptic body, and it removes the per-body rescan that dominates a cold
    source-geometry pass.
    """
    value = os.environ.get('GENERATOR_SOURCE_PAIR_STORE', '')
    return Path(value) if value else None


def full_replay_cache_directory() -> Path | None:
    """Durable cache of the stimulus-only full-population replays; unset disables it.

    The two stimulus-only passes of a full ЦНС experiment depend only on the
    configuration and the stimulus, so a repeat experiment can restore them
    instead of replaying 166 700 cells. Nothing physical is inferred from the
    cache: every entry is re-verified by digest before it is used.
    """
    value = os.environ.get('GENERATOR_FULL_REPLAY_CACHE', '')
    return Path(value) if value else None


def connectome_model_path() -> Path:
    bundled = Path(__file__).resolve().parents[2] / "validation/male-cns-v1/classifier.json"
    if not bundled.is_file():
        bundled = (
            Path(__file__).resolve().parents[1] / "_bundled/validation/male-cns-v1/classifier.json"
        )
    return Path(os.environ.get("GENERATOR_CNS_MODEL_PATH", str(bundled)))
