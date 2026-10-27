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


def connectome_model_path() -> Path:
    bundled = Path(__file__).resolve().parents[2] / "validation/male-cns-v1/classifier.json"
    if not bundled.is_file():
        bundled = (
            Path(__file__).resolve().parents[1] / "_bundled/validation/male-cns-v1/classifier.json"
        )
    return Path(os.environ.get("GENERATOR_CNS_MODEL_PATH", str(bundled)))
