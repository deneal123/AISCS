"""CPU и tool-calling транспорт не выдают модели встроенный executor или секреты."""

import pytest

from local_llm.service.configuration import configuration
from local_llm.service.domain.model import MODEL_ID


def test_cpu_only_fixed_alias_and_no_builtin_tools_or_inherited_network():
    runtime = configuration(
        {
            "LOCAL_LLM_API_KEY": "synthetic-key-" * 4,
            "LLAMA_ARG_TOOLS": "all",
            "LLAMA_ARG_MCP_SERVERS_JSON": "PRIVATE_CAPABILITY",
            "LLAMA_ARG_CONNECT": "1",
            "HTTPS_PROXY": "http://private-proxy",
        }
    )
    command, child = runtime.command, runtime.child_environment
    assert command[command.index("--alias") + 1] == MODEL_ID
    assert command[command.index("--device") + 1] == "none"
    assert command[command.index("--n-gpu-layers") + 1] == "0"
    assert command[command.index("--parallel") + 1] == "1"
    assert {"--jinja", "--no-agent", "--no-webui", "--no-slots", "--offline"} <= set(command)
    assert "synthetic-key" not in str(command)
    assert not any("PRIVATE" in value or "proxy" in value for value in child.values())
    assert not any(name.startswith("LLAMA_ARG_") for name in child)
    assert child["LLAMA_API_KEY"] == "synthetic-key-" * 4
    assert "synthetic-key" not in repr(runtime)
    assert runtime.address == ("127.0.0.1", 8080)
    with pytest.raises(TypeError):
        child["LLAMA_API_KEY"] = "CHANGED"


@pytest.mark.parametrize("key", ["", "short", " " * 40, "secret\n" * 8])
def test_start_refuses_missing_or_invalid_authentication(key):
    with pytest.raises(ValueError, match="key_required"):
        configuration({"LOCAL_LLM_API_KEY": key})


@pytest.mark.parametrize(
    "name,value",
    [
        ("LOCAL_LLM_CONTEXT_SIZE", "32769"),
        ("LOCAL_LLM_CONTEXT_SIZE", "0"),
        ("LOCAL_LLM_THREADS", "99"),
        ("LOCAL_LLM_PORT", "1"),
        ("LOCAL_LLM_HOST", "public.example"),
    ],
)
def test_start_refuses_resource_or_bind_expansion(name, value):
    with pytest.raises(ValueError):
        configuration({"LOCAL_LLM_API_KEY": "synthetic-key-" * 4, name: value})
