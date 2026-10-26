"""Stage verified model files in ephemeral Linux storage before a phase."""

import hashlib
import json
import os
import shutil
from pathlib import Path

root = Path(os.environ["FLYVIS_ROOT_DIR"])
assert root == Path("/tmp/aspa-flyvis")
manifest = json.loads(Path("/work/flyvis-inputs.json").read_text())
for item in manifest["pretrained_files"]:
    source = Path("/work") / item["destination"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"]
    target = root / item["member"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
print(
    "Staged the exact official 50-model ensemble in ephemeral Linux storage", flush=True
)
