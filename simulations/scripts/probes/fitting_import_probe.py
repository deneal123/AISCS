"""Load real model definitions without training or creating substitute datasets."""

import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
source = Path("/work/source")
sys.path.insert(0, str(source))
sys.argv = [str(source / "drosophila_whole_brain_fitting.py")]
module = runpy.run_path(sys.argv[0], run_name="fitting_probe")
assert callable(module["Population"])
assert callable(module["load_syn"])
print("Actual fitting model definitions imported; no training/data substitution")
