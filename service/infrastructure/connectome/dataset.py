"""The complete registered annotated non-glial MaleCNS graph, not a display sample."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow.feather as feather

DATASET_ID = "male-cns:v1.0-annotated-nonglial"
MANIFEST_SHA256 = "742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2"
ANNOTATIONS_SHA256 = "d27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee"
SOURCE_COMMIT = "12f48c702ed170b5bdc4643afa7ce65e952b353d"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 << 20), b""):
            result.update(block)
    return result.hexdigest()


@dataclass
class SparseGraph:
    ids: np.ndarray
    ptr: np.ndarray
    posts: np.ndarray
    counts: np.ndarray
    signs: np.ndarray
    annotations: dict
    provenance: dict

    @property
    def size(self) -> int:
        return len(self.ids)

    def stimulus_indices(self, region: str) -> np.ndarray:
        info = self.annotations
        superclass, kind = np.asarray(info["superclass"]), np.asarray(info["class"])
        nerves = np.asarray([x or "" for x in info["entryNerve"]])
        sides = np.asarray(
            [a or b or "" for a, b in zip(info["rootSide"], info["somaSide"], strict=True)]
        )
        if region == "head":
            mask = (superclass == "cb_sensory") & (kind == "mechanosensory")
        else:
            mask = (superclass == "vnc_sensory") & (kind == "mechanosensory_tactile")
            if region == "abdomen":
                mask &= np.char.startswith(nerves, "AbN")
            elif region == "thorax":
                mask &= np.isin(nerves, ["ProLN", "MesoLN", "MetaLN"])
            else:
                segment, side = region.rsplit("_", 1)
                nerve = {"front": "ProLN", "middle": "MesoLN", "hind": "MetaLN"}[segment]
                mask &= (nerves == nerve) & (sides == {"left": "L", "right": "R"}[side])
        selected = np.flatnonzero(mask).astype(np.int32)
        if not len(selected):
            raise ValueError(f"No registered tactile input population for {region}")
        return selected

    def bridge_groups(self) -> list[np.ndarray]:
        info = self.annotations
        superclass = np.asarray(info["superclass"])
        segment = np.asarray(info["somaNeuromere"])
        sides = np.asarray(info["somaSide"])
        groups = [
            np.flatnonzero(
                (superclass == "vnc_intrinsic") & (segment == section) & (sides == side)
            ).astype(np.int32)
            for section in ("T1", "T2", "T3")
            for side in ("L", "R")
        ]
        if any(not len(group) for group in groups):
            raise ValueError("Missing registered VNC population for the projection adapter")
        return groups


def load_registered_graph(directory: Path) -> SparseGraph:
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("MaleCNS dataset is not prepared")
    if digest(manifest_path) != MANIFEST_SHA256:
        raise ValueError("Unregistered MaleCNS graph manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected in manifest["arrays"].items():
        if digest(directory / name) != expected:
            raise ValueError(f"MaleCNS array checksum mismatch: {name}")
    if digest(directory / "neurons.feather") != ANNOTATIONS_SHA256:
        raise ValueError("MaleCNS annotation checksum mismatch")
    arrays = {
        name: np.load(directory / (name + ".npy"), mmap_mode="r", allow_pickle=False)
        for name in ("ids", "ptr", "posts", "counts", "signs")
    }
    ids, ptr, posts, counts, signs = (
        arrays[key] for key in ("ids", "ptr", "posts", "counts", "signs")
    )
    if (
        len(ids) != 166700
        or len(posts) != 25582938
        or len(counts) != len(posts)
        or ptr.shape != (len(ids) + 1,)
        or signs.shape != ids.shape
        or ptr[0] != 0
        or ptr[-1] != len(posts)
        or (np.diff(ptr) < 0).any()
        or (np.diff(ids) <= 0).any()
        or posts.min() < 0
        or posts.max() >= len(ids)
        or not counts.min() > 0
    ):
        raise ValueError("Malformed or incomplete registered MaleCNS CSR")
    names = [
        "bodyId",
        "superclass",
        "class",
        "type",
        "somaNeuromere",
        "rootSide",
        "somaSide",
        "entryNerve",
        "exitNerve",
        "somaLocation",
        "tosomaLocation",
    ]
    annotations = feather.read_table(directory / "neurons.feather", columns=names).to_pydict()
    if not np.array_equal(ids, np.asarray(annotations["bodyId"], dtype=np.int64)):
        raise ValueError("MaleCNS annotation order disagrees with graph identities")
    return SparseGraph(
        **arrays,
        annotations=annotations,
        provenance={
            "dataset_id": DATASET_ID,
            "manifest_sha256": MANIFEST_SHA256,
            "annotations_sha256": ANNOTATIONS_SHA256,
            "source_commit": SOURCE_COMMIT,
            "source": manifest["source"],
            "license": manifest["license"],
            "selection": manifest["selection"],
            "sources": manifest["sources"],
            "array_sha256": manifest["arrays"],
            "neurons": len(ids),
            "edges": len(posts),
            "coordinate_scale_um": 0.008,
            "coordinate_source": "8 nm voxel soma/to-soma landmarks; not neurite morphology",
        },
    )
