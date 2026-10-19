"""Exact-source dependency prelude for isolated child-process lifecycle probes."""

import hashlib
from pathlib import Path


def allocation_bootstrap() -> str:
    source = (Path(__file__).parents[1] / "service/application/allocations.py").read_text(
        encoding="utf-8"
    )
    digest = hashlib.sha256(source.encode()).hexdigest()
    return (
        "import hashlib,sys,types\n"
        "sys.path.insert(0,'/opt/workspace-sidecar/service')\n"
        f"_allocation_source={source!r}\n"
        f"assert hashlib.sha256(_allocation_source.encode()).hexdigest()=={digest!r}\n"
        "_allocation_module=types.ModuleType('application.allocations')\n"
        "_allocation_module.__file__='/opt/workspace-sidecar/service/application/allocations.py'\n"
        "sys.modules['application.allocations']=_allocation_module\n"
        "exec(compile(_allocation_source,_allocation_module.__file__,'exec'),"
        "_allocation_module.__dict__)\n"
    )
