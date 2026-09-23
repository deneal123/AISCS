"""Print the safe compiled capability manifest for offline release gates."""

from __future__ import annotations

import json

from service.domain.capabilities.runtime import initialize_static_catalog


def main() -> int:
    manifest = initialize_static_catalog().manifest()
    print(json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
