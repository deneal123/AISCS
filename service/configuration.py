"""Проверка окружения и CPU-профиля; ключи не входят в аргументы процесса."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from types import MappingProxyType

from .domain.model import MODEL, MODEL_ID


@dataclass(frozen=True, slots=True)
class RuntimeConfiguration:
    address: tuple[str, int]
    model_path: Path
    command: tuple[str, ...]
    child_environment: Mapping[str, str] = field(repr=False)
    api_key: str = field(repr=False)
    request_timeout_sec: float = 330.0


def bounded(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    value = int(env.get(name, str(default)))
    if not low <= value <= high:
        raise ValueError("local_llm_setting_invalid")
    return value


def configuration(env: Mapping[str, str]) -> RuntimeConfiguration:
    key = env.get("LOCAL_LLM_API_KEY", "")
    if (
        not 32 <= len(key) <= 256
        or not key.isascii()
        or key != key.strip()
        or any(char.isspace() for char in key)
    ):
        raise ValueError("local_llm_key_required")
    host = env.get("LOCAL_LLM_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "0.0.0.0"}:
        raise ValueError("local_llm_host_invalid")
    threads = bounded(env, "LOCAL_LLM_THREADS", 2, 1, 8)
    context = bounded(env, "LOCAL_LLM_CONTEXT_SIZE", 8192, 1024, 32768)
    port = bounded(env, "LOCAL_LLM_PORT", 8080, 1024, 65535)
    timeout = float(env.get("LOCAL_LLM_TIMEOUT_SEC", "330"))
    if not isfinite(timeout) or not 1 <= timeout <= 600:
        raise ValueError("local_llm_setting_invalid")
    model = Path(env.get("LOCAL_LLM_MODEL_DIR", "/models")) / MODEL.filename
    command = [
        env.get("LOCAL_LLM_SERVER", "/opt/llama/llama-server"),
        "--model",
        str(model),
        "--alias",
        MODEL_ID,
        "--host",
        "127.0.0.1",
        "--port",
        "8081",
        "--threads",
        str(threads),
        "--threads-batch",
        str(threads),
        "--ctx-size",
        str(context),
        "--parallel",
        "1",
        # Кеш нескольких контекстов по умолчанию занимает до 8 ГиБ при лимите
        # всего контейнера 1,5 ГиБ. Оставляем рабочий KV-контекст одного слота.
        "--cache-ram",
        "0",
        "--n-predict",
        "2048",
        "--batch-size",
        "256",
        "--ubatch-size",
        "128",
        "--device",
        "none",
        "--n-gpu-layers",
        "0",
        "--temp",
        "0.6",
        "--top-p",
        "0.95",
        "--top-k",
        "20",
        "--repeat-penalty",
        "1.0",
        "--jinja",
        "--no-agent",
        "--no-webui",
        "--no-slots",
        "--no-context-shift",
        "--offline",
        "--log-disable",
    ]
    # Чужие LLAMA_ARG_TOOLS/MCP/CONNECT и прокси не наследуются процессом модели.
    child = {name: env[name] for name in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if name in env}
    child.update(LLAMA_API_KEY=key, LANG="C.UTF-8", LD_LIBRARY_PATH="/opt/llama")
    return RuntimeConfiguration(
        (host, port), model, tuple(command), MappingProxyType(child), key, timeout
    )
