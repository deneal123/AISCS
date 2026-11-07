"""Map candidate synapse locations to reconstructed SWC components.

Components are disconnected in the source reconstruction. A geometric nearest
segment is only a candidate, not evidence of a biological synapse or an
electrical connection between fragments.
"""

from __future__ import annotations

from service.infrastructure.connectome.morphology import neurite_landmark
from service.infrastructure.connectome.synapse_morphology import nearest_swc_segments


def fragment_roots(swc: str) -> dict[int, int]:
    """Return a deterministic root for every validated SWC vertex."""
    neurite_landmark(swc)
    parents = {}
    for line in swc.splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            fields = line.split()
            parents[int(fields[0])] = int(fields[6])
    roots = {}
    for node in parents:
        current, chain = node, []
        while current not in roots and parents[current] != -1:
            chain.append(current)
            current = parents[current]
        root = roots.get(current, current)
        roots[current] = root
        roots.update((item, root) for item in chain)
    return roots


def map_fragment_candidates(swc: str, points_um, *, point_batch_size=16):
    """Report the fragment of each nearest-cable candidate without connecting them."""
    roots = fragment_roots(swc)
    mapped = nearest_swc_segments(swc, points_um, point_batch_size=point_batch_size)
    return {**mapped, 'component_root_ids': [roots[child] for child in mapped['child_node_ids']],
            'component_count': len(set(roots.values())),
            'interpretation': ('nearest reconstructed cable and its SWC component; '
                               'not proof of synaptic ownership or fragment connectivity')}
