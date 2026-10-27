"""Single source of the authored geometry, shared by validation, UI and solver."""

import numpy as np


def sections_for_cell(cell: int) -> list:
    x, y = (cell // 2) * 85 - 85, (cell % 2) * 70 - 35
    return [
        ("soma", (x, y, -8), (x, y, 8), 12, 3),
        ("dendrite", (x, y, -8), (x - 35, y, -55), 2, 5),
        ("axon", (x, y, 8), (x + 45, y, 75), 1.5, 7),
    ]


def local_geometry() -> dict:
    starts, ends, diameters, cells, soma_ids = [], [], [], [], []
    for cell in range(6):
        soma_ids.append(len(starts) + 1)
        for _, first, last, diameter, count in sections_for_cell(cell):
            first, last = np.array(first), np.array(last)
            for segment in range(count):
                starts.append((first + (last - first) * segment / count).tolist())
                ends.append((first + (last - first) * (segment + 1) / count).tolist())
                diameters.append(diameter)
                cells.append(cell)
    return {
        "starts_um": starts,
        "ends_um": ends,
        "diameters_um": diameters,
        "cell_ids": cells,
        "soma_segment_ids": soma_ids,
    }
