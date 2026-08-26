"""Explicit local compatibility mode for direct sidecar handler tests."""

from __future__ import annotations

import os

# Production compose enables mandatory backend coordination.  These unit tests
# exercise handlers without booting the backend coordinator by design.
os.environ.setdefault("WORKSPACE_ALLOW_UNCOORDINATED_TESTS", "true")
