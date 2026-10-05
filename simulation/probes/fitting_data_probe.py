"""Exercise the actual model constructor; never supply fabricated FlyWire data."""

import json
import runpy
from pathlib import Path

module = runpy.run_path("/work/probes/fitting_import_probe.py")
try:
    module["module"]["Population"](flywire_version="630")
except FileNotFoundError as error:
    Path("/work/data-prerequisite.json").write_text(
        json.dumps({"status": "blocked_missing_registered_data", "error": str(error), "filename": error.filename}, indent=2),
        encoding="utf-8",
    )
    raise
