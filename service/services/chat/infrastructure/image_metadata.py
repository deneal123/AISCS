"""Strict legacy image metadata parsing; no source payload in failures."""

import json


def last_image_key(metadata: object) -> str | None:
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            raise ValueError("image_metadata_invalid") from None
    if metadata is None:
        return None
    if not isinstance(metadata, dict):
        raise ValueError("image_metadata_invalid")
    files = metadata.get("generated_files")
    if files is None:
        return None
    if not isinstance(files, list):
        raise ValueError("image_metadata_invalid")
    for item in files:
        if not isinstance(item, dict) or item.get("kind") != "image":
            continue
        key = item.get("file_key")
        if isinstance(key, str) and key.strip() and not any(ord(char) < 32 for char in key):
            return key
    return None
