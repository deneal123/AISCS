"""Deterministic scientific generator; independent from platform service packages."""

import tomllib
from importlib.metadata import version
from pathlib import Path

_project = Path(__file__).resolve().parent.parent / "pyproject.toml"
if _project.is_file():
    with _project.open("rb") as _stream:
        __version__ = tomllib.load(_stream)["project"]["version"]
else:
    __version__ = version("aspa-generator")
