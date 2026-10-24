"""Закреплённые публичные артефакты: без плавающего latest или пользовательских URL."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Artifact:
    filename: str
    url: str
    sha256: str
    size: int


MODEL_ID = "qwen2.5-1.5b-instruct"
MODEL_REVISION = "91cad51170dc346986eccefdc2dd33a9da36ead9"
RUNTIME_VERSION = "b11846"
MODEL = Artifact(
    filename="qwen2.5-1.5b-instruct-q4_k_m.gguf",
    url=(
        "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
        + MODEL_REVISION
        + "/qwen2.5-1.5b-instruct-q4_k_m.gguf"
    ),
    sha256="6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
    size=1117320736,
)
