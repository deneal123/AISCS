"""Закреплённые публичные артефакты: без плавающего latest или пользовательских URL."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Artifact:
    filename: str
    url: str
    sha256: str
    size: int


MODEL_ID = "lfm2.5-1.2b-instruct"
MODEL_REVISION = "8ed288026e23958ad9dfa92d53ed773a8eee7125"
RUNTIME_VERSION = "b11846"
MODEL = Artifact(
    filename="LFM2.5-1.2B-Instruct-Q4_K_M.gguf",
    url=(
        "https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF/resolve/"
        + MODEL_REVISION
        + "/LFM2.5-1.2B-Instruct-Q4_K_M.gguf"
    ),
    sha256="b1b3de114215d9507409a662a501a631095a479a419584e8a2ded6304b19b4f5",
    size=730895168,
)
