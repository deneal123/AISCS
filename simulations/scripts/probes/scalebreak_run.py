"""Keep numerical failure visible while rendering the valid recorded outputs."""

import subprocess
import sys
from pathlib import Path

base = Path(__file__).resolve().parent
status = subprocess.run(
    [sys.executable, "-u", str(base / "scalebreak_probe.py")], check=False
).returncode
if Path("/work/exports/functional.json").is_file():
    plotted = subprocess.run(
        [sys.executable, str(base / "scalebreak_plot.py")], check=False
    ).returncode
    if plotted:
        raise SystemExit(plotted)
raise SystemExit(status)
