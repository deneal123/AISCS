import json
from pathlib import Path


def scene_context() -> dict:
    path = Path(__file__).with_name("flybody-scene-context.json")
    return json.loads(path.read_text(encoding="utf-8"))


def registered_scene_contexts() -> list[dict]:
    legacy = json.loads(Path(__file__).with_name("scene-context.json").read_text(encoding="utf-8"))
    return [scene_context(), legacy]
