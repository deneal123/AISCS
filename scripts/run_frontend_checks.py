"""Frontend checks that pre-commit can run without a POSIX shell.

Windows has no usable `bash`: `C:/Windows/System32/bash.exe` is a WSL relay into the
docker-desktop distribution, which has no `/bin/bash`, so every hook written as
`bash -lc "cd frontend && ..."` failed with `execvpe(/bin/bash) failed` instead of
checking anything. The same applies to `python3`, which on this machine is the Microsoft
Store stub that exits 9009 after printing one word.

This script replaces that shell glue: it resolves the frontend directory from its own
location, refuses to guess when dependencies are absent (a loud skip, not a silent pass),
and runs the real tool with the working directory the tool expects.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / 'frontend'


def _node() -> str:
    node = shutil.which('node')
    if node is None:
        raise SystemExit('ПРОПУСК — node не найден в PATH')
    return node


def _missing(relative: str, install_hint: str) -> str:
    return f'ПРОПУСК — нет frontend/{relative}, выполните {install_hint}'


def eslint() -> int:
    binary = FRONTEND / 'node_modules' / 'eslint' / 'bin' / 'eslint.js'
    if not binary.is_file():
        print(_missing('node_modules/eslint', 'npm ci'))
        return 0
    command = [
        _node(),
        str(binary),
        'src/**/*.{js,jsx}',
        '--max-warnings=0',
    ]
    return subprocess.run(command, cwd=FRONTEND, check=False).returncode


def jest(extra: list[str]) -> int:
    binary = FRONTEND / 'node_modules' / 'jest' / 'bin' / 'jest.js'
    if not binary.is_file():
        print(_missing('node_modules/jest', 'npm ci'))
        return 0
    if not (FRONTEND / 'tests' / 'unit').is_dir():
        print('ПРОПУСК — нет frontend/tests/unit')
        return 0
    command = [_node(), str(binary), '--ci', '--runInBand', *extra]
    return subprocess.run(command, cwd=FRONTEND, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('check', choices=('eslint', 'jest'))
    # `parse_known_args`, а не `parse_args`: аргументы jest начинаются с `--`
    # (`--watchAll=false`), и argparse считал бы их своими. Всё, что осталось,
    # уходит jest как есть, поэтому перечень его флагов здесь не дублируется.
    options, extra = parser.parse_known_args(argv)
    if options.check == 'eslint':
        if extra:
            print(f'ПРОПУСК лишних аргументов у eslint: {extra}')
            return 2
        return eslint()
    return jest(extra)


if __name__ == '__main__':
    sys.exit(main())
