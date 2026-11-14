"""Bulk population replay: authenticated cache preparation into CUDA batches.

The reference path prepares every cell with NEURON and solves cells one batch at
a time. This module feeds the same solver from the authenticated packed-geometry
cache through the NEURON-free fast_cable kernel, keeps every identity check of
the cache reader, and bounds each device batch by its padded segment cost.
It is independent-cell replay, not network feedback.
"""

from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .fast_prepare import iter_prepared_chunks

__all__ = ["iter_cell_batches", "solve_population"]


def _segments(cell):
    return len(cell["geometry"]["area"])


def _event_grid(geometry, default_nseg):
    """Keep an explicitly prepared nonuniform grid when attaching events."""
    edges = geometry['edge_node_ids']
    if geometry.get('grid') is not None:
        from .grid_contract import grid_configuration

        grid = geometry['grid']
        grid_configuration(grid, edges)
        return list(grid)
    segments = geometry['segment_index']
    if len(edges) != len(segments):
        raise ValueError('Invalid population event grid')
    return [(int(edge), int(segment), default_nseg)
            for edge, segment in zip(edges, segments, strict=True)]


def _plan_bucket(cells, *, segment_budget, max_padding, max_cells):
    """Split one width-homogeneous bucket into padding-bounded batches."""
    from .batching import plan_batches

    counts = [_segments(cell) for cell in cells]
    for index_batch in plan_batches(counts, max_cells=max_cells,
                                    max_padded_segments=segment_budget,
                                    max_padding_ratio=max_padding):
        yield [cells[index] for index in index_batch]


def width_order(metadata):
    """Return chunk positions ordered by ascending mean cell width.

    A prepared cell is large (hundreds of kilobytes of geometry), so a planner
    cannot pool the whole population; it keeps only a small rolling window. But
    cache chunks hold morphologies in body-id order, and body ids are not
    width-sorted, so any small window mixes a 100-segment cell with a
    40 000-segment one and the padding bound then flushes tiny batches.

    The manifest already records each neuron's vertex count, so the decode order
    can be planned up front without decoding anything: visit chunks by mean
    width. Positions are preserved, so per-chunk identity checks are unaffected.
    Returns None if the manifest lacks the counts.
    """
    chunks = metadata["chunks"]
    widths = []
    for descriptor in chunks:
        neurons = descriptor.get("neurons") or ()
        counts = [item.get("count") for item in neurons]
        counts = [value for value in counts if type(value) is int and value > 0]
        if not counts:
            return None
        widths.append(sum(counts) / len(counts))
    return sorted(range(len(chunks)), key=lambda index: (widths[index], index))


# The cell-major kernels read only these keys. Everything else a prepared cell
# carries (starts_um, ends_um, midpoints_um, edge_node_ids, field_mv) is dead
# weight on the producer thread, and a pooled batch holds thousands of cells:
# measured 0.7 MB per prepared cell, which is what OOM-killed the 6 000-cell
# pool at full population.
_GEOMETRY_KEYS = ("parents", "conductances", "segment_nodes", "area", "grid")
_CELL_KEYS = ("id", "field_current_na", "events", "initial_voltage_mv", "initial_gates")


def _narrow(cell, reduce_geometry, reroot_centre, slim, recording=False, events=False):
    """Reduce (and optionally re-root) one cell; thread-safe."""
    geometry = reduce_geometry(cell["geometry"], verify=False)[0]
    if reroot_centre is not None:
        parents, conductances, segments = reroot_centre(
            geometry["parents"], geometry["conductances"], geometry["segment_nodes"])
        geometry = dict(geometry, parents=parents, conductances=conductances,
                        segment_nodes=segments)
    if slim:
        # .copy() is not cosmetic: the prepared arrays are VIEWS into the decoded
        # chunk, so keeping even one view keeps that whole chunk (~14 MB of
        # vertices) resident. A pooled batch spans dozens of chunks and the pool
        # is thousands of cells, which is what pushed a whole-population run out
        # of memory on a host with ~6 GB free. Detaching costs ~55 KB of memcpy
        # per cell (9 GB over the population, a few seconds spread over the
        # reduce pool) and lets every finished chunk be freed.
        geometry_keys = _GEOMETRY_KEYS + (('starts_um', 'ends_um', 'midpoints_um',
                          'endpoint_radii_um') if recording else ())
        if recording or events:
            geometry_keys += ('edge_node_ids', 'segment_index')
        cell_keys = _CELL_KEYS + (('morphology_sha256',) if recording else ())
        geometry = {key: (np.ascontiguousarray(geometry[key]).copy()
                          if isinstance(geometry[key], np.ndarray) else geometry[key])
                    for key in geometry_keys}
        cell = {key: (np.ascontiguousarray(cell[key]).copy()
                      if isinstance(cell[key], np.ndarray) else cell[key])
                for key in cell_keys}
        return {**cell, "geometry": geometry}
    return dict(cell, geometry=geometry)


def _reduce_all(cells, reduce_geometry, reroot_centre, slim=False, pool=None, recording=False,
                events=False):
    """Narrow every tree, optionally re-rooting it at the graph centre.

    One cell costs 1.6 ms of reduce at the population mean, which is 273 s for
    the whole population on a SINGLE producer thread - more than the GPU solve
    it is supposed to hide behind, and the reason the device idled for 110 s of
    a 420 s run. The work is per-cell and independent, and reduction.py is
    compiled with nogil, so it fans out over a small thread pool while the
    producer keeps decoding.
    """
    def narrow(cell):
        return _narrow(cell, reduce_geometry, reroot_centre, slim, recording=recording,
                       events=events)

    if pool is None or len(cells) < 2:
        return [narrow(cell) for cell in cells]
    return list(pool.map(narrow, cells))


def iter_cell_batches(metadata, *, audited_sources, params, segment_budget, workers=4,
                      limit=None, progress=None, window_cells=4096, max_padding=3.0,
                      max_cells=3000, pool_cells=12000, refine=None, on_invalid=None,
                      store_bounds=False, replacement_factory=None, on_replacement=None,
                      cell_transform=None):
    """Yield prepared-cell lists whose padded segment cost stays within budget.

    The solver pads every batch to its widest member, so the bound applies to
    max(segments) * len(batch). Manifest order is NOT width-sorted, so greedy
    manifest-order packing starts a new batch as soon as a wide morphology
    arrives and leaves batches an order of magnitude below the budget
    (measured: a 12 000 000-segment budget yielded ~500-cell batches and no
    throughput gain). Cells are therefore pooled by width bit length - at most
    a 2x spread inside a bucket - and each bucket is planned by
    batching.plan_batches, which bounds padded segments and the padding ratio.
    Chunks are additionally visited in ascending mean width (the manifest
    records vertex counts, so no decoding is needed to plan this), otherwise
    body-id order mixes a 100-segment cell with a 40 000-segment one in every
    window and padding flushes tiny batches. The pool is drained as a WHOLE
    whenever it reaches pool_cells, and the drained prefix is planned by
    batching.plan_batches. Draining whole is the important part: any rule that
    flushes a single width bucket while it is still growing cuts that bucket in
    half and the remainder becomes a 1-3 cell batch (measured 274 of 342
    batches under 200 cells with a staleness rule, versus 12 of 82 when the
    whole pool is drained). A whole-pool drain is also self-limiting in memory:
    it always empties completely, so the pool never exceeds pool_cells by more
    than one chunk.

    A morphology wider than the whole budget is rejected rather than truncated.
    """
    if type(segment_budget) is not int or segment_budget < 1:
        raise ValueError("Invalid segment budget")
    if type(window_cells) is not int or window_cells < 1:
        raise ValueError("Invalid preparation window")
    if max_cells is not None and (type(max_cells) is not int or max_cells < 1):
        raise ValueError("Invalid cell limit per batch")
    if type(pool_cells) is not int or pool_cells < 1:
        raise ValueError("Invalid pool limit")
    if cell_transform is not None and not callable(cell_transform):
        raise ValueError('Invalid population cell transform')
    limit_cells = max_cells if max_cells is not None else window_cells

    order = width_order(metadata)
    # The pool is drained WHOLE, never per width band: a band flush while the
    # band is still being read splits it and the remainder becomes a 1-3 cell
    # batch. Measured offline over the real manifest (sim-plan2.py): draining
    # 12 000-cell pools gives 82 batches, median 2 880 cells, only 12 under 200;
    # any staleness/band rule gives 126-779 batches with most under 200.
    pool = []
    for bodies, cells, chunk in iter_prepared_chunks(
            metadata, audited_sources=audited_sources, params=params, workers=workers,
            limit=limit, progress=progress, order=order, on_invalid=on_invalid,
            store_bounds=store_bounds, replacement_factory=replacement_factory,
            on_replacement=on_replacement):
        del bodies, chunk
        if cell_transform is not None:
            transformed = []
            for original in cells:
                replacement = cell_transform(original)
                if (not isinstance(replacement, dict)
                        or replacement.get('id') != original.get('id')
                        or replacement.get('morphology_sha256')
                        != original.get('morphology_sha256')):
                    raise ValueError('Population cell transform identity mismatch')
                transformed.append(replacement)
            cells = transformed
        # Refine each chunk before it joins the pool: narrowing and re-rooting a
        # tree is a pure per-cell transform, and doing it here keeps the pool
        # holding only the compact cells the solver needs instead of the full
        # prepared records. A pooled batch is thousands of cells and the full
        # record measured 0.7 MB each, which is what OOM-killed whole-population
        # runs on a host with ~6 GB free.
        if refine is not None:
            cells = refine(cells)
        for cell in cells:
            if _segments(cell) > segment_budget:
                raise ValueError("A morphology exceeds the batch segment budget")
            pool.append(cell)
        if len(pool) >= pool_cells:
            yield from _plan_bucket(pool, segment_budget=segment_budget,
                                    max_padding=max_padding, max_cells=limit_cells)
            pool = []
    if pool:
        yield from _plan_bucket(pool, segment_budget=segment_budget,
                                max_padding=max_padding, max_cells=limit_cells)


def solve_population(metadata, stimulus_midpoint, rate_table, *, audited_sources, params,
                     segment_budget, output_budget_bytes, dt_ms=.05, window_steps=25,
                     block_threads=32, reduce_trees=True, workers=4, limit=None,
                     progress=None, check_cancelled=None, timing_sink=None,
                     window_sink=None, window_cells=4096, max_padding=3.0,
                     max_cells=3000, pool_cells=12000, cell_warps=1,
                     block_cell_segments=40000, allow_table_clamp=False, prefetch=2,
                     reroot=False, reduce_workers=1, on_invalid=None,
                     device_window_factory=None, event_factory=None,
                     replacement_factory=None, on_replacement=None,
                     recording_max_selected=None, require_cell_major=False,
                     cell_major_block_threads=512, cell_transform=None):
    """Yield (ids, result) for each bounded batch of an authenticated population.

    window_sink(ids, start, end, rows) receives the same ordered sample windows
    the reference replay emits; without it only final voltages are kept, which
    is the cheap path for population-scale screening.

    If supplied, on_invalid(body_id, error_code) runs on the preparation
    thread. The caller must retain these receipts and mark results partial.
    Without a callback the first rejected cell aborts the population replay.
    """
    from .batch_solver import solve_prepared_batch

    if type(prefetch) is not int or not 1 <= prefetch <= 8:
        raise ValueError("Invalid preparation prefetch depth")
    if type(require_cell_major) is not bool or (require_cell_major and window_sink is not None):
        raise ValueError('Invalid required cell-major mode')
    if (type(cell_major_block_threads) is not int
            or cell_major_block_threads not in (32, 64, 128, 256, 512)):
        raise ValueError('Invalid cell-major block threads')
    if on_invalid is not None and not callable(on_invalid):
        raise ValueError("Invalid rejected-cell callback")
    if ((device_window_factory is not None and not callable(device_window_factory))
            or (device_window_factory is not None and window_sink is not None)):
        raise ValueError("Invalid population recording configuration")
    if event_factory is not None and not callable(event_factory):
        raise ValueError('Invalid population event factory')
    if (recording_max_selected is not None and
            (type(recording_max_selected) is not int or recording_max_selected < 0
             or device_window_factory is None)):
        raise ValueError('Invalid population recording selection bound')
    if type(reroot) is not bool:
        raise ValueError("Invalid re-root flag")
    if type(reduce_workers) is not int or not 1 <= reduce_workers <= 16:
        raise ValueError("Invalid reduce worker count")
    reduce_geometry = None
    reroot_centre = None
    if reduce_trees:
        from .reduced_tree import reduce_geometry
    if reroot:
        from .reroot_tree import reroot_centre

    # One thread prepares and reduces the NEXT batch while the GPU solves the
    # current one. Measured on the full population: prepare+reduce ran at
    # ~64 s/100 s for 166 700 cells and the endpoint method is a generator, so
    # without this the two phases serialise and the host is idle while the GPU
    # works and the reverse. The queue is bounded so the producer cannot run
    # ahead and hold the whole population in memory.
    cell_major = window_sink is None
    # Packing a 3 000-cell batch into the (cell, node) columns costs 0.5-0.8 s of
    # host time and sat in front of every launch: measured 90-118 s of a 478 s
    # full-population run. It must NOT run on the prepare thread (tried: the run
    # went 475 -> 555 s, because preparing and packing then serialise and the GPU
    # starves), but a SEPARATE packer thread fed by the prepare thread hides it
    # completely behind the GPU solve.

    stop = threading.Event()

    def put_until_stopped(target, item):
        while not stop.is_set():
            try:
                target.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def produce():
        pool = None
        try:
            refine = None
            marker = [time.perf_counter()]
            clock = time.perf_counter
            if reduce_geometry is not None:
                if reduce_workers > 1:
                    pool = ThreadPoolExecutor(max_workers=reduce_workers,
                                              thread_name_prefix="population-reduce")
                else:
                    pool = None

                def refine(cells, *, _sink=timing_sink, _pool=pool, _marker=marker):
                    # The idle gap since the previous refine is the time the
                    # producer spent reading, authenticating and preparing this
                    # chunk, so this splits "prepare" into its two halves without
                    # touching fast_prepare's own ordering guarantees.
                    started = clock()
                    if _sink is not None:
                        _sink('decode', started - _marker[0])
                    try:
                        return _reduce_all(cells, reduce_geometry, reroot_centre,
                                           slim=cell_major, pool=_pool,
                                           recording=device_window_factory is not None,
                                           events=event_factory is not None)
                    finally:
                        if _sink is not None:
                            _sink('reduce', clock() - started)
                        _marker[0] = clock()
            for cells in iter_cell_batches(
                    metadata, audited_sources=audited_sources, params=params,
                    segment_budget=segment_budget, workers=workers, limit=limit,
                    progress=progress, window_cells=window_cells,
                    max_padding=max_padding, max_cells=max_cells,
                    pool_cells=pool_cells, refine=refine, on_invalid=on_invalid,
                    store_bounds=device_window_factory is not None,
                    replacement_factory=replacement_factory, on_replacement=on_replacement,
                    cell_transform=cell_transform):
                if recording_max_selected is not None:
                    from .batching import plan_cell_major_window_batches

                    groups = plan_cell_major_window_batches(
                        [len(cell['geometry']['parents']) for cell in cells],
                        [len(cell['geometry']['segment_nodes']) for cell in cells],
                        [min(recording_max_selected, len(cell['geometry']['segment_nodes']))
                         for cell in cells], max_cells=len(cells),
                        samples=len(stimulus_midpoint), window_steps=window_steps,
                        output_budget_bytes=output_budget_bytes, max_padding_ratio=max_padding,
                        generic_fallback=not require_cell_major)
                else:
                    groups = [list(range(len(cells)))]
                for group in groups:
                    batch = [cells[index] for index in group]
                    if event_factory is not None:
                        ids = [cell['id'] for cell in batch]
                        events = event_factory(tuple(ids))
                        if (not isinstance(events, dict) or set(events) != set(ids)
                                or any(not isinstance(events[body], list) for body in ids)):
                            raise ValueError('Invalid population event schedule')
                        updated = []
                        for cell in batch:
                            selected = events[cell['id']]
                            geometry = cell['geometry']
                            if selected:
                                grid = _event_grid(geometry, params.nseg)
                                geometry = dict(geometry, grid=grid)
                            updated.append(dict(cell, geometry=geometry, events=selected))
                        batch = updated
                    if not put_until_stopped(prepared, (batch, None)):
                        return
            put_until_stopped(prepared, (None, None))
        except BaseException as exc:  # forwarded to the consumer, never swallowed
            put_until_stopped(prepared, (None, exc))
        finally:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)

    def pack():
        """Turn reduced cells into cell-major columns, off the solve thread.

        Packing 3 000 cells costs 0.5-0.8 s of host time and measured 90-118 s of
        a 478 s full-population run, all of it serialised in front of the launch.
        It cannot share the prepare thread (that measured 475 -> 555 s: preparing
        and packing then serialise against each other and the GPU starves), so it
        gets its own stage. The GPU only needs the columns of the batch it is
        about to launch, which is exactly what this stage produces one batch
        ahead.
        """
        try:
            while not stop.is_set():
                try:
                    cells, failure = prepared.get(timeout=0.1)
                except queue.Empty:
                    continue
                if failure is not None or cells is None:
                    put_until_stopped(waiting, (cells, failure))
                    return
                extra = None
                if cell_major:
                    extra = build_cell_major(cells, [cell["geometry"] for cell in cells])
                if not put_until_stopped(waiting, (cells, extra)):
                    return
        except BaseException as exc:
            put_until_stopped(waiting, (None, exc))

    if cell_major:
        # One packed batch in flight is enough: the packer is faster than the GPU,
        # so a deeper queue only holds more (cell, node) columns in host memory,
        # and a 3 000-cell batch of those is ~750 MB.
        waiting = queue.Queue(maxsize=1)
        prepared = queue.Queue(maxsize=prefetch)
        from .batch_solver import build_cell_major
        threading.Thread(target=pack, name="population-pack", daemon=True).start()
    else:
        # No packing stage: the producer hands batches straight to the consumer.
        waiting = prepared = queue.Queue(maxsize=prefetch)
    threading.Thread(target=produce, name="population-prepare", daemon=True).start()
    try:
        while True:
            try:
                cells, extra = waiting.get(timeout=0.1)
            except queue.Empty:
                if check_cancelled is not None:
                    check_cancelled()
                continue
            if isinstance(extra, BaseException):
                raise extra
            if cells is None:
                break
            if check_cancelled is not None:
                check_cancelled()
            ids = [cell["id"] for cell in cells]
            sink = None
            if window_sink is not None:
                def sink(start, end, rows, *, batch_ids=tuple(ids)):
                    if tuple(row.get("id") for row in rows) != batch_ids:
                        raise ValueError("GPU window identity mismatch")
                    window_sink(batch_ids, start, end, rows)

            device_options = {}
            if device_window_factory is not None:
                recording = device_window_factory(cells)
                if (not isinstance(recording, dict) or set(recording) !=
                        {'recording_coefficients', 'selected_indices', 'sink'}
                        or not callable(recording['sink'])):
                    raise ValueError('Invalid population recording configuration')
                if recording_max_selected is not None and (
                    not isinstance(recording['selected_indices'], dict)
                    or any(not isinstance(value, list) or len(value) > recording_max_selected
                           for value in recording['selected_indices'].values())
                ):
                    raise ValueError('Population recording selection exceeds planned bound')
                def device_sink(start, end, rows, *, batch_ids=tuple(ids),
                                accept=recording['sink']):
                    if tuple(row.get('id') for row in rows) != batch_ids:
                        raise ValueError('GPU window identity mismatch')
                    accept(start, end, rows)
                device_options = {'device_window_sink': device_sink,
                                  'recording_coefficients': recording['recording_coefficients'],
                                  'selected_indices': recording['selected_indices']}

            result = solve_prepared_batch(
                cells, stimulus_midpoint, rate_table,
                output_budget_bytes=output_budget_bytes, dt_ms=dt_ms,
                window_steps=window_steps, window_sink=sink,
                allow_table_clamp=allow_table_clamp,
                check_cancelled=check_cancelled, timing_sink=timing_sink,
                reduce_trees=False, block_threads=block_threads,
                cell_major=sink is None,
                record_traces=sink is not None or device_window_factory is not None,
                cell_warps=cell_warps, block_cell_segments=block_cell_segments,
                cell_major_block_threads=cell_major_block_threads,
                cell_major_packed=extra, require_cell_major=require_cell_major, **device_options)
            yield list(ids), result
    finally:
        # A stopped consumer must not leave producers blocked on full queues.
        # In-flight decoding and GPU work can only stop at their next boundary.
        stop.set()
