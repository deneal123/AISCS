"""Package version for source deployments and installed distributions."""

import tomllib
from importlib.metadata import version
from pathlib import Path

_project = Path(__file__).resolve().parent.parent / "pyproject.toml"
if _project.is_file():
    with _project.open("rb") as _stream:
        VERSION = tomllib.load(_stream)["project"]["version"]
else:
    VERSION = version("gpthub-agents")
