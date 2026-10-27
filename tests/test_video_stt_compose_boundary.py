from pathlib import Path

import pytest


@pytest.mark.parametrize("filename", ["docker-compose.dev.yaml", "docker-compose.yaml"])
def test_backend_receives_existing_video_key_alias(filename):
    source = (Path(__file__).resolve().parents[2] / "docker" / filename).read_text(encoding="utf-8")
    backend = source.split("\n  backend:", 1)[1].split("\n  postgres:", 1)[0]
    assert 'AGENTS__VIDEO_API_KEY: "${VIDEO_API_KEY:-}"' in backend
    assert 'VIDEO_API_KEY: "${VIDEO_API_KEY:-}"' in source
