"""Chunk the original retinal arithmetic without changing stimulus geometry."""

import json
from pathlib import Path

import torch


def install(receipt_path=None):
    from flyvis.datasets.rendering import eye

    original_inside = eye.is_inside_hex
    original_call = eye.HexEye.__call__

    def chunked_inside(x, y, *args, **kwargs):
        vertices = None
        mask = None
        for start in range(0, len(x), 2048):
            vertices, part = original_inside(
                x[start : start + 2048], y[start : start + 2048], *args, **kwargs
            )
            if mask is None:
                mask = torch.empty(
                    (len(x), part.shape[1]), dtype=part.dtype, device=part.device
                )
            mask[start : start + len(part)] = part
        return vertices, mask

    def chunked_call(self, stim, mode="mean", n_chunks=1):
        # Native moving-bar rendering supplies flattened frames. Preserve the
        # native route for resizing and median filters; only split receptor cols.
        if stim.ndim != 2 or mode not in {"mean", "sum"}:
            return original_call(self, stim, mode, n_chunks)
        parts = []
        for start in range(0, self.is_inside.shape[1], 16):
            value = (stim[:, :, None] * self.is_inside[:, start : start + 16]).sum(
                dim=1
            )
            if mode == "mean":
                value = value / self.kernel_sum[start : start + 16]
            parts.append(value)
        return torch.cat(parts, dim=1)

    # Compare the same native geometry and arithmetic before installing wrappers.
    small = eye.HexEye(19, 3, device="cpu")
    stim = (
        torch.arange(
            small.monitor_height_px * small.monitor_width_px * 2, dtype=torch.float64
        ).reshape(2, -1)
        / 100
    )
    reference = original_call(small, stim)
    compared = chunked_call(small, stim)
    torch.testing.assert_close(reference, compared, rtol=1e-12, atol=1e-12)
    x, y = (
        torch.arange(4099, dtype=torch.float16) % 23,
        torch.arange(4099, dtype=torch.float16) % 19,
    )
    args = (torch.tensor([1.0, 2.0, 3.0]), torch.tensor([2.0, 3.0, 4.0]), 2.0, 0.0)
    v1, m1 = original_inside(x, y, *args, device="cpu")
    v2, m2 = chunked_inside(x, y, *args, device="cpu")
    assert torch.equal(v1, v2) and torch.equal(m1, m2)
    eye.is_inside_hex = chunked_inside
    eye.HexEye.__call__ = chunked_call
    (
        Path(receipt_path)
        if receipt_path
        else Path("/work/exports/render-chunking.json")
    ).write_text(
        json.dumps(
            {
                "status": "passed",
                "change": "process-local wrappers split points and receptor columns; native geometry, dtype and reduction over pixels retained",
                "pixel_chunk": 2048,
                "receptor_chunk": 16,
                "geometry_parity_exact": True,
                "mean_max_abs_difference": float((reference - compared).abs().max()),
                "source_files_modified": False,
                "context": "Unwrapped native MovingEdge construction was killed with exit137 at peak6405455872 bytes in the prior run",
            },
            indent=2,
        )
        + "\n"
    )
