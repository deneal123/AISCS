import pytest

from service.infrastructure.connectome.fragment_mapping import (
    fragment_roots,
    map_fragment_candidates,
)


def test_component_mapping_uses_parent_graph_not_input_order():
    swc = ('4 3 1250 125 0 1 3\n2 3 125 0 0 1 1\n'
           '3 1 1250 0 0 1 -1\n1 1 0 0 0 1 -1\n')
    assert fragment_roots(swc) == {1: 1, 2: 1, 3: 3, 4: 3}
    result = map_fragment_candidates(swc, [[.5, 0, 0], [10, .5, 0]])
    assert result['child_node_ids'] == [2, 4]
    assert result['component_root_ids'] == [1, 3]
    assert result['component_count'] == 2
    assert 'not proof' in result['interpretation']


def test_invalid_or_cyclic_parent_graph_is_rejected():
    with pytest.raises(ValueError):
        fragment_roots('1 3 0 0 0 1 2\n2 3 125 0 0 1 1\n')
    with pytest.raises(ValueError):
        fragment_roots('1 3 0 0 0 1 99\n')
