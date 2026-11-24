"""Bounded, authenticated target geometries for synapse-pair mapping."""

from collections import OrderedDict

from service.infrastructure.connectome.synapse_morphology import prepare_cached_morphology
from service.infrastructure.stimulation.geometry_cache.selected import SelectedCache


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


def _prepare_entry(entry, *, target_ids, derived_target):
    """Validate one decoded entry and return its prepared target geometry."""
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
    if int(skeleton['body_id']) not in target_ids:
        raise ValueError('Unexpected cached target identity')
    return int(skeleton['body_id']), (skeleton, geometry)


def prepare_cached_targets(graph, target_ids, *, geometry_cache, workers=1,
                           derived_target=None, snapshot=None):
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
    if snapshot is not None and not isinstance(snapshot, SelectedCache):
        raise ValueError('Invalid authenticated geometry snapshot')
    entries = (snapshot or _open_snapshot(graph, geometry_cache, workers=workers)).entries(
        target_ids, workers=workers)
    targets = {}
    for entry in entries:
        body, prepared = _prepare_entry(entry, target_ids=target_ids,
                                        derived_target=derived_target)
        if body in targets:
            raise ValueError('Unexpected cached target identity')
        targets[body] = prepared
    if set(targets) != set(target_ids):
        raise ValueError('Cached target geometry is incomplete')

    def get(body):
        if type(body) is not int or body not in targets:
            raise ValueError('Target outside verified cache batch')
        return targets[body]

    return get


def _open_snapshot(graph, geometry_cache, *, workers):
    return SelectedCache(geometry_cache['directory'],
        expected_manifest_sha256=geometry_cache['expected_manifest_sha256'],
        graph_ids=graph.ids, graph_sha256=graph.provenance['manifest_sha256'],
        source_index=geometry_cache['source_index'], source_audit=geometry_cache['source_audit'],
        workers=workers)


def population_target_provider(graph, morphology_sha256, *, geometry_cache, workers=1,
                               derived_target=None, cache_size=128, snapshot=None):
    """Resolve arbitrary registered targets with bounded, verified geometry caching.

    The authenticated snapshot is opened once.  A miss decodes the whole chunk
    that holds the requested target, so the neighbouring cells it will be asked
    for later are prepared for free instead of re-reading the chunk per cell.
    This does not establish synaptic function or electrical equivalence of any
    derived geometry.  Every returned morphology must match the solver identity.
    """
    if (not isinstance(morphology_sha256, dict) or not morphology_sha256
            or set(morphology_sha256) != {int(body) for body in graph.ids}
            or type(cache_size) is not int or not 1 <= cache_size <= 4096):
        raise ValueError('Invalid population target identities')
    if snapshot is not None and not isinstance(snapshot, SelectedCache):
        raise ValueError('Invalid authenticated geometry snapshot')
    hashes = morphology_sha256.copy()
    graph_hash = graph.provenance['manifest_sha256']
    cache = OrderedDict()
    failures = {}
    state = {'snapshot': snapshot}

    def _pool(values):
        # A worker pool costs more to start than a single small chunk is worth.
        return 1 if len(values) <= 2 else workers

    def authenticated():
        if state['snapshot'] is None:
            state['snapshot'] = _open_snapshot(graph, geometry_cache, workers=workers)
        return state['snapshot']

    def prepare(body):
        snapshot_now = authenticated()
        siblings = [value for value in snapshot_now.chunk_bodies(body) if value in hashes]
        for candidate in siblings:
            if candidate in cache:
                cache.move_to_end(candidate)
        missing = [value for value in siblings if value not in cache]
        if missing:
            # One or two cells do not pay for a worker pool: the pool costs more
            # to start than the chunk it would read.
            for entry in snapshot_now.entries(missing, workers=_pool(missing)):
                held = int(entry['skeleton']['body_id'])
                try:
                    held, prepared = _prepare_entry(entry, target_ids=set(siblings),
                                                    derived_target=derived_target)
                except ValueError as exc:
                    # A neighbour that cannot be prepared (the known zero-edge
                    # cell without a repair policy) must not fail an unrelated
                    # request, but it may never be served silently either.
                    failures[held] = exc
                    continue
                failures.pop(held, None)
                if held in cache:
                    raise ValueError('Unexpected cached target identity')
                if prepared[0].get('body_id') != str(held) or prepared[0].get('sha256') != hashes[held]:
                    raise ValueError('Population target morphology digest mismatch')
                cache[held] = prepared
                while len(cache) > cache_size:
                    cache.popitem(last=False)
        if body not in cache:
            if body in failures:
                raise failures[body]
            raise ValueError('Cached target geometry is incomplete')
        cache.move_to_end(body)
        return cache[body]

    def prefetch(bodies):
        """Load many targets through one ordered pass over their chunks.

        A target list scattered across the population touches a few cells of
        many chunks; asking for them one at a time re-decodes a whole chunk per
        cell.  One pass per batch decodes each needed chunk once.  The cache is
        left as it would be after the same requests, so behaviour is unchanged.
        """
        snapshot_now = authenticated()
        wanted = []
        for body in bodies:
            if (type(body) is not int or body not in hashes
                    or body in cache or body in failures):
                continue
            wanted.append(body)
        if not wanted:
            return 0
        siblings = {}
        for body in wanted:
            for value in snapshot_now.chunk_bodies(body):
                if value in hashes:
                    siblings.setdefault(value, None)
        # Only the first window is loaded; the caller walks the targets in
        # chunk order, so every later chunk is decoded once on its own miss.
        held, used = [], 0
        for value in siblings:
            if value in cache:
                continue
            if used >= cache_size:
                break
            held.append(value)
            used += 1
        loaded = 0
        for entry in snapshot_now.entries(held, workers=_pool(held)):
            body = int(entry['skeleton']['body_id'])
            try:
                body, prepared = _prepare_entry(entry, target_ids=set(siblings),
                                                derived_target=derived_target)
            except ValueError as exc:
                failures[body] = exc
                continue
            failures.pop(body, None)
            if prepared[0].get('body_id') != str(body) or prepared[0].get('sha256') != hashes[body]:
                raise ValueError('Population target morphology digest mismatch')
            cache[body] = prepared
            loaded += 1
            while len(cache) > cache_size:
                cache.popitem(last=False)
        return loaded

    def get(body):
        if (type(body) is not int or body not in hashes
                or graph.provenance.get('manifest_sha256') != graph_hash):
            raise ValueError('Invalid population target identity')
        return prepare(body)

    def order(bodies):
        """Return the given targets in the order their chunks are packed.

        Walking targets in this order turns a scattered request into one pass
        over the geometry snapshot instead of one whole-chunk decode per cell.
        """
        snapshot_now = authenticated()
        unique = {body for body in bodies if type(body) is int and body in hashes}
        return sorted(unique, key=lambda body: (snapshot_now.chunk_index(body) or 0, body))

    get.prefetch = prefetch
    get.order = order
    return get
