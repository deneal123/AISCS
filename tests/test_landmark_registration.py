import numpy as np
import pytest

from service.infrastructure.stimulation.landmark_registration import fit_landmark_registration


def test_recovers_transform_and_reports_independent_error():
    source = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1.0]])
    rotation = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1.0]])
    target = 2 * source @ rotation + [3, 4, 5]
    heldout = np.array([[2.0, 3, 4], [-1, 3, 2]])
    truth = 2 * heldout @ rotation + [3, 4, 5]
    result = fit_landmark_registration(source, target, heldout, truth, allow_scale=True)
    assert result["scale"] == pytest.approx(2)
    np.testing.assert_allclose(result["rotation_row_vectors"], rotation, atol=1e-12)
    assert result["heldout_rmse"] < 1e-12
    truth[1, 0] += 1
    result = fit_landmark_registration(source, target, heldout, truth, allow_scale=True)
    assert result["heldout_max"] == pytest.approx(1)
    assert result["heldout_rmse"] == pytest.approx(2**-0.5)


def test_rejects_overlap_and_degenerate_landmarks_and_forbids_reflection():
    points = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
    with pytest.raises(ValueError, match="distinct"):
        fit_landmark_registration(points, points, points[:1], points[:1])
    with pytest.raises(ValueError, match="three dimensions"):
        fit_landmark_registration(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], points, [[2, 2, 2]], [[2, 2, 2]]
        )
    mirrored = points * [-1, 1, 1]
    result = fit_landmark_registration(points, mirrored, [[2, 3, 4]], [[-2, 3, 4]])
    assert np.linalg.det(result["rotation_row_vectors"]) == pytest.approx(1)
    assert result["heldout_rmse"] > 0
