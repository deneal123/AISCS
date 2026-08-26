"""Workspace sidecar entrypoint: HTTP composition is in ``presentation.http``."""

import sys

from presentation import http as _implementation

# Keep ``uvicorn app:app`` and direct legacy imports stable while keeping the
# service root free of route orchestration.
app = _implementation.app
sys.modules[__name__] = _implementation

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=_implementation.PORT)
