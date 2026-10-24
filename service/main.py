"""Композиция проверенной модели, llama runtime и OpenAI-совместимого HTTP API."""

import os

from .configuration import configuration
from .domain.model import MODEL
from .infrastructure.llama.runtime import run
from .infrastructure.llama.transport import LlamaTransport
from .infrastructure.models.artifacts import verified
from .presentation.http import Gateway


def main() -> int:
    try:
        runtime = configuration(os.environ)
        if not verified(runtime.model_path, MODEL):
            raise ValueError("local_llm_model_unverified")
    except (ValueError, OSError) as error:
        code = str(error) if isinstance(error, ValueError) else "local_llm_model_unavailable"
        print(code if code.startswith("local_llm_") else "local_llm_setting_invalid", flush=True)
        return 1
    try:
        server = Gateway(runtime.address, runtime.api_key, upstream=LlamaTransport(runtime.api_key))
    except OSError:
        print("local_llm_bind_unavailable", flush=True)
        return 1
    return run(server, runtime.command, runtime.child_environment)
