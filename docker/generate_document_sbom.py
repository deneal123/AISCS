#!/usr/bin/env python3
"""Generate a deterministic CycloneDX inventory from installed Debian packages."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def main() -> None:
    raw = subprocess.check_output(
        ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n"], text=True
    )
    components = []
    for line in sorted(raw.splitlines()):
        name, separator, version = line.partition("\t")
        if not separator or not name or not version:
            continue
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:deb/debian/{name}@{version}",
            }
        )
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "container", "name": "gpthub-document-runtime"}},
        "components": components,
    }
    target = Path("/opt/document-runtime/sbom.cdx.json")
    target.write_text(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
