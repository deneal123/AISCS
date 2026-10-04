"""Atomic directory exchange: a killed publisher must never remove the project path."""

from __future__ import annotations

import shlex


def project_exchange_command(project: str, staged: str) -> str:
    # Both directories are private, validated paths on the same workspace filesystem.
    # Unsupported kernels/filesystems fail closed: do not fall back to two renames.
    script = (
        "import ctypes,os,sys; "
        "library=ctypes.CDLL(None,use_errno=True); "
        "rename=library.renameat2; "
        "rename.argtypes=[ctypes.c_int,ctypes.c_char_p,"
        "ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]; "
        "rename.restype=ctypes.c_int; "
        "result=rename(-100,os.fsencode(sys.argv[1]),-100,os.fsencode(sys.argv[2]),2); "
        "\nif result != 0:\n raise RuntimeError('source_exchange_failed')\n"
    )
    return f"python -c {shlex.quote(script)} {shlex.quote(project)} {shlex.quote(staged)}; "


def exchange_marker(project: str, token: str) -> str:
    return f"{project}/.gpthub-document/source-exchange-{token}"
