import numpy as np
import pytest

from service.infrastructure.connectome.segmentation_connectivity import assess_local_connectivity


def test_connected_with_nonzero_origin():
    labels = np.zeros((6, 5, 5), dtype=np.uint64)
    labels[1:5, 2, 2] = 91
    result = assess_local_connectivity(labels, body_id=91, origin_voxel=[100, 200, 300],
                                       source_voxel=[101, 202, 302], target_voxel=[104, 202, 302])
    assert result['source_matches'] and result['target_matches']
    assert result['same_component_in_cutout']
    assert result['nearest_source_component_to_target_voxels'] == 0


def test_same_label_does_not_prove_connectivity():
    labels = np.zeros((5, 5, 5), dtype=np.uint64)
    labels[1, 1, 1] = labels[3, 3, 3] = 91
    result = assess_local_connectivity(labels, body_id=91, origin_voxel=[0, 0, 0],
                                       source_voxel=[1, 1, 1], target_voxel=[3, 3, 3])
    assert result['target_matches'] and not result['same_component_in_cutout']
    assert result['nearest_source_component_to_target_voxels'] is None


def test_nearby_component_and_truncated_search_are_explicit():
    labels = np.zeros((5, 5, 5), dtype=np.uint64)
    labels[1:4, 2, 2] = 91
    result = assess_local_connectivity(labels, body_id=91, origin_voxel=[0, 0, 0],
                                       source_voxel=[1, 2, 2], target_voxel=[4, 2, 2],
                                       projection_radius_voxels=2)
    assert not result['target_matches'] and not result['same_component_in_cutout']
    assert result['nearest_source_component_to_target_voxels'] == 1
    assert not result['projection_search_complete']


def test_rejects_invalid_and_unowned_input():
    labels = np.zeros((3, 3, 3), dtype=np.uint64)
    kwargs = dict(body_id=91, origin_voxel=[0, 0, 0], source_voxel=[0, 0, 0],
                  target_voxel=[2, 2, 2])
    assert not assess_local_connectivity(labels, **kwargs)['source_matches']
    with pytest.raises(ValueError):
        assess_local_connectivity(labels, **{**kwargs, 'body_id': True})
    with pytest.raises(ValueError):
        assess_local_connectivity(labels, **{**kwargs, 'target_voxel': [3, 2, 2]})
