"""Bounded, authenticated target geometries for synapse-pair mapping."""

from collections import OrderedDict

from service.infrastructure.connectome.synapse_morphology import prepare_cached_morphology
from service.infrastructure.stimulation.geometry_cache.selected import iter_selected_cache


def known_derived_target(directories):
    """Prepare the verified zero-edge contraction for geometric mapping only.

    This does not authorize using the derived geometry in a coupled solver.
    """
    from service.infrastructure.connectome.morphology_repository import read_skeleton
    from service.infrastructure.connectome.synapse_morphology import _prepare_segments
    from service.infrastructure.stimulation.experimental_gpu.known_geometry_repair import (
        KNOWN_SOURCE_SHA256,
    )
    from service.infrastructure.stimulation.zero_edge_transform import contract_zero_edge

    def prepare(entry):
        source = entry['skeleton']
        if (source.get('body_id') != '842998'
                or source.get('sha256') != KNOWN_SOURCE_SHA256):
            raise ValueError('Unsupported derived target identity')
        original = read_skeleton(842998, directories, expected_sha256=KNOWN_SOURCE_SHA256)
        derived, receipt = contract_zero_edge(original['swc'].encode('utf8'),
            expected_sha256=KNOWN_SOURCE_SHA256, parent_id=75, child_id=76)
        skeleton = {'body_id': '842998', 'sha256': receipt['derived_sha256'],
                    'transformation': receipt}
        return skeleton, _prepare_segments(derived.decode('utf8'))

    return prepare


def prepare_cached_targets(graph, target_ids, *, geometry_cache, workers=1,
                           derived_target=None):
    """Load a small target batch only after every selected chunk is verified.

    The returned callable is valid only for this snapshot and selected batch.
    A caller-supplied correction must retain both source and derived identities.
    """
    if (not isinstance(target_ids, list) or not 1 <= len(target_ids) <= 128
            or any(type(body) is not int or body <= 0 for body in target_ids)
            or len(set(target_ids)) != len(target_ids)):
        raise ValueError('Invalid cached target batch')
    if derived_target is not None and not callable(derived_target):
        raise ValueError('Invalid derived target policy')
    entries = iter_selected_cache(geometry_cache['directory'],
        expected_manifest_sha256=geometry_cache['expected_manifest_sha256'], graph_ids=graph.ids,
        graph_sha256=graph.provenance['manifest_sha256'],
        source_index=geometry_cache['source_index'], source_audit=geometry_cache['source_audit'],
        selected_ids=target_ids, workers=workers)
    targets = {}
    for entry in entries:
        body = int(entry['skeleton']['body_id'])
        if derived_target is not None and body == 842998:
            skeleton, geometry = derived_target(entry)
            receipt = skeleton.get('transformation') if isinstance(skeleton, dict) else None
            if (not isinstance(receipt, dict)
                    or receipt.get('source_sha256') != entry['skeleton']['sha256']
                    or receipt.get('derived_sha256') != skeleton.get('sha256')
                    or skeleton.get('body_id') != str(body)):
                raise ValueError('Invalid derived target provenance')
        else:
            skeleton, geometry = prepare_cached_morphology(entry)
        body = int(skeleton['body_id'])
        if body not in target_ids or body in targets:
            raise ValueError('Unexpected cached target identity')
        targets[body] = (skeleton, geometry)
    if set(targets) != set(target_ids):
        raise ValueError('Cached target geometry is incomplete')

    def get(body):
        if type(body) is not int or body not in targets:
            raise ValueError('Target outside verified cache batch')
        return targets[body]

    return get


def population_target_provider(graph, morphology_sha256, *, geometry_cache, workers=1,
                               derived_target=None, cache_size=16):
    """Resolve arbitrary registered targets with bounded, verified geometry caching.

    This does not establish synaptic function or electrical equivalence of any
    derived geometry. Every returned morphology must match the solver identity.
    """
    if (not isinstance(morphology_sha256, dict) or not morphology_sha256
            or set(morphology_sha256) != {int(body) for body in graph.ids}
            or type(cache_size) is not int or not 1 <= cache_size <= 128):
        raise ValueError('Invalid population target identities')
    hashes = morphology_sha256.copy()
    graph_hash = graph.provenance['manifest_sha256']
    cache = OrderedDict()

    def get(body):
        if (type(body) is not int or body not in hashes
                or graph.provenance.get('manifest_sha256') != graph_hash):
            raise ValueError('Invalid population target identity')
        if body not in cache:
            prepared = prepare_cached_targets(graph, [body], geometry_cache=geometry_cache,
                                               workers=workers, derived_target=derived_target)(body)
            if prepared[0].get('body_id') != str(body) or prepared[0].get('sha256') != hashes[body]:
                raise ValueError('Population target morphology digest mismatch')
            cache[body] = prepared
            if len(cache) > cache_size:
                cache.popitem(last=False)
        else:
            cache.move_to_end(body)
        return cache[body]

    return get
