"""Source-bound input adapter; it does not modify the validated LIF solver."""

from pathlib import Path

import numpy as np
import pyarrow.feather as feather

from service.infrastructure.connectome.dataset import ANNOTATIONS_SHA256, digest


class NotumGraph:
    def __init__(self, graph, directory: Path):
        path = directory / "neurons.feather"
        if digest(path) != ANNOTATIONS_SHA256:
            raise ValueError("Unregistered MaleCNS annotation file")
        columns = feather.read_table(path, columns=["bodyId", "subclass"]).to_pydict()
        if not np.array_equal(graph.ids, np.asarray(columns["bodyId"], dtype=np.int64)):
            raise ValueError("Notum annotations do not match registered graph")
        info = graph.annotations
        mask = (
            (np.asarray(info["superclass"]) == "vnc_sensory")
            & (np.asarray(info["class"]) == "mechanosensory_tactile")
            & (np.asarray(info["entryNerve"]) == "PDMN")
            & (np.asarray(columns["subclass"]) == "notum")
        )
        self.indices = np.flatnonzero(mask).astype(np.int32)
        if len(self.indices) != 214:
            raise ValueError("Unexpected notum population")
        self.graph = graph

    def stimulus_indices(self, region: str) -> np.ndarray:
        return self.indices if region == "notum" else self.graph.stimulus_indices(region)

    def __getattr__(self, name):
        return getattr(self.graph, name)
