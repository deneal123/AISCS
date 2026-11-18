"""Grouped, per-source synapse pairs read from one sequential pass over the source.

`SynapseBatchIndex.query` re-materialises every record batch of the 6.31 GB
connectome source once per body it is asked about. Measured on real cells that
costs 921 us per synapse pair, about 33 h for the whole population, because a
single body touches a few thousand pages of a file that mixes all bodies.

This module reads a store that was produced by ONE sequential pass over the
same source: rows are filtered to registered presynaptic bodies and placed in
per-body slots, so an outgoing query is a contiguous slice plus a JSON-shaped
record construction. The row set and the row order are identical to the
reference index, which is what makes it usable as a drop-in pair source.
"""

import hashlib
import json
from pathlib import Path

import numpy as np

FORMAT = "malecns-source-pairs-v1"
FILES = ("body.npy", "offset.npy", "post.npy", "position.npy")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(directory, *, source_md5, ids_sha256):
    """Describe a finished store so a later open can authenticate every array."""
    directory = Path(directory)
    body = np.load(directory / "body.npy")
    offsets = np.load(directory / "offset.npy")
    return {"format": FORMAT, "source_md5": source_md5, "ids_sha256": ids_sha256,
            "bodies": int(len(body)), "rows": int(offsets[-1]),
            "sha256": {name: _sha256(directory / name) for name in FILES}}


class SourcePairStore:
    """Read outgoing synapse pairs by body without touching the packed source."""

    def __init__(self, directory, expected_manifest_sha256=None):
        directory = Path(directory)
        manifest_path = directory / "manifest.json"
        payload = manifest_path.read_bytes()
        self.directory = directory
        self.manifest = json.loads(payload)
        self.manifest_sha256 = hashlib.sha256(payload).hexdigest()
        if (expected_manifest_sha256 is not None
                and self.manifest_sha256 != expected_manifest_sha256):
            raise ValueError("Source pair store manifest changed")
        if (self.manifest.get("format") != FORMAT
                or not isinstance(self.manifest.get("source_md5"), str)
                or not isinstance(self.manifest.get("ids_sha256"), str)
                or type(self.manifest.get("bodies")) is not int
                or type(self.manifest.get("rows")) is not int
                or set(self.manifest.get("sha256", {})) != set(FILES)):
            raise ValueError("Invalid source pair store manifest")
        for name in FILES:
            if _sha256(directory / name) != self.manifest["sha256"][name]:
                raise ValueError(f"Source pair store array changed: {name}")
        self.body = np.load(directory / "body.npy")
        self.offset = np.load(directory / "offset.npy")
        self.post = np.load(directory / "post.npy", mmap_mode="r")
        self.position = np.load(directory / "position.npy", mmap_mode="r")
        if (self.body.ndim != 1 or self.offset.shape != (len(self.body) + 1,)
                or len(self.post) != self.manifest["rows"]
                or self.position.shape != (len(self.post), 3)
                or np.any(np.diff(self.offset) < 0)
                or self.offset[-1] != len(self.post)):
            raise ValueError("Invalid source pair store arrays")

    def query(self, body_id, direction, limit=None, *, partner_ids=None):
        """Return the same outgoing page shape as the packed synapse index."""
        if direction != "outgoing" or partner_ids is not None or limit is not None:
            raise ValueError("Source pair store only serves complete outgoing pages")
        if type(body_id) is not int or body_id <= 0:
            raise ValueError("Invalid neuron ID")
        position = int(np.searchsorted(self.body, body_id))
        if position >= len(self.body) or int(self.body[position]) != body_id:
            raise ValueError("Neuron is not in registered graph")
        start, stop = int(self.offset[position]), int(self.offset[position + 1])
        posts = self.post[start:stop]
        coordinates = self.position[start:stop]
        rows = [{"body_pre": body_id, "body_post": int(post),
                 "x_pre": int(coordinate[0]), "y_pre": int(coordinate[1]),
                 "z_pre": int(coordinate[2]),
                 "x_post": 0, "y_post": 0, "z_post": 0}
                for post, coordinate in zip(posts.tolist(), coordinates.tolist(),
                                            strict=True)]
        return {"body_id": str(body_id), "direction": "outgoing",
                "total": len(rows), "returned": len(rows), "truncated": False,
                "coordinate_frame": "male-cns-v1.0-native-8nm",
                "source_md5": self.manifest["source_md5"], "pairs": rows}