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


def narrow_cell_cache_directory() -> Path | None:
    """Durable cache of narrowed population cells; unset disables it.

    Decoding a morphology chunk and reducing its tree are functions of the
    geometry and the field configuration alone, yet a full experiment pays for
    them four times: 530 s of decoding and 603 s of reduction in a single
    166 700-cell pass. The cache stores the narrowed cells once so later passes
    read them instead, reproducing the same batches over the same cells.
    """
    value = os.environ.get('GENERATOR_NARROW_CELL_CACHE', '')
    return Path(value) if value else None


def recording_coefficient_cache_directory() -> Path | None:
    """Durable cache of per-batch recording coefficients; unset disables it.

    The recording coefficients are one float per segment, a function of the
    reduced geometry and the electrode pair alone. They are recomputed on every
    pass: on the wide tail that construction measured 159.8 s of a 384 s shard,
    and removing it entirely saved 96 s. The cache stores them per batch, keyed
    by the batch geometry, so a hit is one read and no arithmetic.
    """
    value = os.environ.get('GENERATOR_RECORDING_COEFFICIENT_CACHE', '')
    return Path(value) if value else None


def full_control_policy() -> str:
    """Whether the paired zero-stimulus pass runs, or is declared structurally empty.

    The control branch drives the same population with a zero stimulus. A solver
    whose only drive is that stimulus cannot depolarise any cell from rest, so the
    branch has no threshold crossing by construction, and a measurement of it
    (2.68e-09 uV against a 1.7175 uV threshold, 0 events in 166 700 cells) only
    confirms the arithmetic. 'omitted' therefore skips a whole population pass
    and publishes a control archive that declares zero events per cell, labelled
    control_omitted in the manifest and the preview. 'required' runs the pass and
    measures it, which is what a new stimulation model should do before its first
    release.
    """
    value = os.environ.get('GENERATOR_FULL_CONTROL', 'omitted')
    if value not in ('required', 'omitted'):
        raise ValueError("GENERATOR_FULL_CONTROL must be 'required' or 'omitted'")
    return value


def full_pause_directory() -> Path | None:
    """Durable checkpoint directory for the full experiment; unset disables pausing.

    A pass takes about twenty minutes, so a host restart or a pause request costs
    a whole population unless the pass can stop at a batch boundary and continue
    from there. The checkpoint is a file, not a signal, so it survives the restart
    that a cancellation performs; nothing in it is trusted without its digest.
    """
    value = os.environ.get('GENERATOR_FULL_PAUSE', '')
    return Path(value) if value else None


def connectome_model_path() -> Path:
    bundled = Path(__file__).resolve().parents[2] / "validation/male-cns-v1/classifier.json"
    if not bundled.is_file():
        bundled = (
            Path(__file__).resolve().parents[1] / "_bundled/validation/male-cns-v1/classifier.json"
        )
    return Path(os.environ.get("GENERATOR_CNS_MODEL_PATH", str(bundled)))