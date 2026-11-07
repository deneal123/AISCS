"""Fit a similarity transform and report independent landmark errors.

This is a numerical tool, not a registration of MaleCNS to any body. Inputs
must be independently established anatomical correspondences in the same units.
"""

from __future__ import annotations

import numpy as np


def fit_landmark_registration(source, target, heldout_source, heldout_target, *, allow_scale=False):
    """Fit proper rotation, translation and optional positive isotropic scale.

    Report errors only on supplied held-out correspondences. A small error on
    a few landmarks does not validate tissues, electrodes or full surfaces.
    """
    if type(allow_scale) is not bool:
        raise ValueError("Scale setting must be boolean")
    train_source, train_target, test_source, test_target = (
        np.asarray(points, dtype=np.float64)
        for points in (source, target, heldout_source, heldout_target)
    )
    for points, minimum in (
        (train_source, 4),
        (train_target, 4),
        (test_source, 1),
        (test_target, 1),
    ):
        if (
            points.ndim != 2
            or points.shape[1] != 3
            or len(points) < minimum
            or not np.isfinite(points).all()
        ):
            raise ValueError("Landmarks must be finite three-dimensional coordinates")
    if train_source.shape != train_target.shape or test_source.shape != test_target.shape:
        raise ValueError("Landmark correspondence counts differ")
    if (
        len(np.unique(train_source, axis=0)) != len(train_source)
        or len(np.unique(train_target, axis=0)) != len(train_target)
        or len(np.unique(test_source, axis=0)) != len(test_source)
        or len(np.unique(test_target, axis=0)) != len(test_target)
        or any(np.array_equal(row, sample) for row in train_source for sample in test_source)
        or any(np.array_equal(row, sample) for row in train_target for sample in test_target)
    ):
        raise ValueError("Landmarks must be distinct across fitting and validation")
    source_mean, target_mean = train_source.mean(axis=0), train_target.mean(axis=0)
    centered_source, centered_target = train_source - source_mean, train_target - target_mean
    if np.linalg.matrix_rank(centered_source) < 3 or np.linalg.matrix_rank(centered_target) < 3:
        raise ValueError("Fitting landmarks must span three dimensions")
    covariance = centered_source.T @ centered_target
    if np.linalg.matrix_rank(covariance) < 3:
        raise ValueError("Landmark correspondence is numerically degenerate")
    u, singular, vt = np.linalg.svd(covariance)
    correction = np.eye(3)
    correction[-1, -1] = 1 if np.linalg.det(u @ vt) > 0 else -1
    rotation = u @ correction @ vt
    scale = (
        float(np.sum(singular * np.diag(correction)) / np.sum(centered_source**2))
        if allow_scale
        else 1.0
    )
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid registration scale")
    translation = target_mean - scale * (source_mean @ rotation)
    residuals = scale * (test_source @ rotation) + translation - test_target
    distances = np.linalg.norm(residuals, axis=1)
    if not np.isfinite(distances).all():
        raise ValueError("Nonfinite registration error")
    return {
        "rotation_row_vectors": rotation,
        "scale": scale,
        "translation": translation,
        "fit_count": len(train_source),
        "heldout_count": len(test_source),
        "heldout_errors": distances,
        "heldout_rmse": float(np.sqrt(np.mean(distances**2))),
        "heldout_max": float(distances.max()),
        "interpretation": "numerical landmark fit; anatomical registration not established",
    }
