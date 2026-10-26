"""Apply one documented device-selection compatibility change to owned work copies."""

import hashlib
import json
from pathlib import Path

expected = {
    "model/train.py": "e04e85118037e46d8ab8120657b6f03acfa4910565f41d76e7ff38014db93f6f",
    "experiment/main.py": "e035168ee9fd87caabeb440732b360ce929e96f2b3c60b23fb2739981ad10ade",
}
needle = "torch.set_default_tensor_type('torch.cuda.FloatTensor')"
replacement = (
    "torch.set_default_tensor_type('torch.FloatTensor')  # explicit CPU evaluation only"
)
receipt = Path("/work/cpu-compatibility.json")
records = json.loads(receipt.read_text()) if receipt.exists() else []
for name, digest in expected.items():
    path = Path("/work/source") / name
    current = path.read_bytes()
    normalized = current.replace(b"\r\n", b"\n")
    text = normalized.decode()
    if replacement in text:
        assert (
            hashlib.sha256(text.replace(replacement, needle).encode()).hexdigest()
            == digest
        )
        assert any(
            item["file"] == name
            and item["after_sha256"] == hashlib.sha256(current).hexdigest()
            for item in records
        )
        continue
    assert hashlib.sha256(normalized).hexdigest() == digest and text.count(needle) == 1
    updated = text.replace(needle, replacement).encode()
    path.write_bytes(updated)
    records.append(
        {
            "file": name,
            "before_sha256": hashlib.sha256(current).hexdigest(),
            "before_lf_sha256": digest,
            "after_sha256": hashlib.sha256(updated).hexdigest(),
            "change": "global tensor device CUDA -> CPU only; equations and parameters unchanged",
            "scope": "owned working copy only; original upstream checkout unchanged",
        }
    )
    receipt.write_text(json.dumps(records, indent=2) + "\n")
print(
    "Documented CPU device selection applied to two work-copy entry points", flush=True
)
