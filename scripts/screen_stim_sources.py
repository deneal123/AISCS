"""Resume paired model screening without treating failures as negative responses."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from itertools import islice
from pathlib import Path

import neuron
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_full_morphology import MANIFEST_SHA256, registered_ids  # noqa: E402
from service.application.screening import source_screening  # noqa: E402
from service.domain import pulse_train  # noqa: E402
from service.domain.contracts.field.graph import FieldGraphConfig  # noqa: E402
from service.infrastructure.connectome import (  # noqa: E402
    forced_network,
    kernel,
    morphology,
    morphology_repository,
)
from service.infrastructure.stimulation import (  # noqa: E402
    point_field,
    source_selection,
    swc_reference,
    virtual_current,
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _step(chain, value):
    return hashlib.sha256(bytes.fromhex(chain) + _canonical(value)).hexdigest()


def _check_row(row, body, duration, dt, field_coupling='extracellular'):
    statuses = {'source_missing', 'disconnected_morphology', 'invalid_or_ambiguous',
                'control_crossing', 'no_crossing', 'stimulus_only_crossing'}
    if not isinstance(row, dict) or row.get('body_id') != body or row.get('status') not in statuses:
        raise ValueError('Screening record does not match the candidate')
    status = row['status']
    keys = {'body_id', 'status'}
    if field_coupling == 'virtual_current':
        keys.add('fallback_runs')
        if type(row.get('fallback_runs')) is not int or not 0 <= row['fallback_runs'] <= 2:
            raise ValueError('Invalid reference fallback count')
    if status in {'control_crossing', 'no_crossing', 'stimulus_only_crossing'}:
        keys.add('morphology_sha256')
        if not isinstance(row.get('morphology_sha256'), str) or not re.fullmatch(
                r'[a-f0-9]{64}', row['morphology_sha256']):
            raise ValueError('Screening record lacks morphology provenance')
    if status == 'stimulus_only_crossing':
        keys.add('selection')
        selection = row.get('selection')
        if (not isinstance(selection, dict)
                or set(selection) != {'child_node_id', 'sampling_fraction', 'segment_index',
                                      'first_sample_ms', 'event_ticks_ms', 'interpretation'}
                or type(selection['child_node_id']) is not int or selection['child_node_id'] <= 0
                or type(selection['segment_index']) is not int or selection['segment_index'] < 0
                or selection['interpretation'] != (
                    'earliest sampled threshold crossing; not a validated spike')
                or not isinstance(selection['event_ticks_ms'], list)
                or not selection['event_ticks_ms']
                or any(type(tick) is not int or not 1 <= tick <= duration
                       for tick in selection['event_ticks_ms'])
                or any(a >= b for a, b in zip(selection['event_ticks_ms'],
                                              selection['event_ticks_ms'][1:], strict=False))
                or type(selection['sampling_fraction']) not in (float, int)
                or not 0 < selection['sampling_fraction'] < 1
                or type(selection['first_sample_ms']) not in (float, int)
                or not 0 < selection['first_sample_ms'] <= duration):
            raise ValueError('Invalid screening source selection')
        first = selection['first_sample_ms']
        nearest = round(first)
        snapped = nearest if abs(first - nearest) <= 1e-9 and nearest != 0 else first
        if (abs(first / dt - round(first / dt)) > 1e-6
                or selection['event_ticks_ms'][0] != math.ceil(snapped)):
            raise ValueError('Screening source timing is inconsistent')
    if set(row) != keys:
        raise ValueError('Unexpected screening record fields')
    _canonical(row)


def _header(ids, simulation, threshold_mv, graph_hash, workers=1, field_coupling='extracellular'):
    if (not isinstance(ids, list) or not ids or any(type(i) is not int or i <= 0 for i in ids)
            or not isinstance(simulation, dict)
            or len(ids) != len(set(ids)) or not isinstance(graph_hash, str)
            or not re.fullmatch(r'[a-f0-9]{64}', graph_hash)
            or type(workers) is not int or not 1 <= workers <= 4
            or field_coupling not in ('extracellular', 'virtual_current')
            or (field_coupling == 'virtual_current' and simulation.get('nseg_per_edge', 1) != 1)):
        raise ValueError('Invalid registered candidate list')
    source_screening.validate_screen_request(ids, simulation, threshold_mv)
    algorithm = hashlib.sha256()
    modules = [source_screening, source_selection, swc_reference, morphology,
               morphology_repository, point_field, forced_network, kernel, pulse_train,
               virtual_current]
    for module in modules:
        algorithm.update(module.__name__.encode() + b'\0' + Path(module.__file__).read_bytes())
    algorithm.update(Path(__file__).read_bytes())
    header = {'kind': 'header', 'format': 'paired-stim-screen-v1', 'graph_sha256': graph_hash,
              'ids_sha256': hashlib.sha256(_canonical(ids)).hexdigest(), 'neurons': len(ids),
              'simulation': simulation, 'threshold_mv': threshold_mv,
              'workers': workers, 'field_coupling': field_coupling,
              'threshold_guard_mv': (source_screening.VIRTUAL_THRESHOLD_GUARD_MV
                                     if field_coupling == 'virtual_current' else None),
              'algorithm_sha256': algorithm.hexdigest(), 'numpy_version': np.__version__,
              'neuron_version': neuron.__version__,
              'interpretation': 'uncalibrated model screening; not physiological excitation'}
    return json.loads(_canonical(header))


def verified_source_cells(ids, path: Path, simulation, *, threshold_mv, graph_hash):
    """Read a complete ledger and return candidates for the graph, failing closed.

    A control crossing, absent morphology, or ambiguous model output is not a
    negative result and prevents a claim that every cell was resolved.
    """
    with path.open(encoding='utf8') as stream:
        raw_header = json.loads(stream.readline())
    if not isinstance(raw_header, dict):
        raise ValueError('Invalid screening header')
    header = _header(ids, simulation, threshold_mv, graph_hash, raw_header.get('workers'),
                     raw_header.get('field_coupling'))
    duration, dt = int(simulation['duration_ms']), simulation.get('dt_ms', .025)
    chain = hashlib.sha256(_canonical(header)).hexdigest()
    selected, unresolved, fallback_runs = [], [], 0
    with path.open(encoding='utf8') as stream:
        first = stream.readline()
        if not first.endswith('\n') or json.loads(first) != header:
            raise ValueError('Screening file has incompatible provenance')
        for body in ids:
            line = stream.readline()
            if not line.endswith('\n'):
                raise ValueError('Screening file is incomplete')
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('Invalid screening record')
            digest = row.pop('chain_sha256', None)
            _check_row(row, body, duration, dt, header['field_coupling'])
            fallback_runs += row.get('fallback_runs', 0)
            chain = _step(chain, row)
            if digest != chain:
                raise ValueError('Screening record checksum mismatch')
            if row['status'] == 'stimulus_only_crossing':
                selection = row['selection']
                selected.append({'body_id': body, 'child_node_id': selection['child_node_id'],
                                 'sampling_fraction': selection['sampling_fraction'],
                                 'threshold_mv': threshold_mv,
                                 'morphology_sha256': row['morphology_sha256']})
            elif row['status'] != 'no_crossing':
                unresolved.append({'body_id': body, 'status': row['status']})
        footer = stream.readline()
        if (not footer.endswith('\n') or json.loads(footer) != {
                'kind': 'footer', 'neurons': len(ids), 'chain_sha256': chain} or stream.read(1)):
            raise ValueError('Screening file is incomplete or has an invalid footer')
    return {'selected': selected, 'unresolved': unresolved, 'screened': len(ids),
            'chain_sha256': chain, 'complete': True, 'reference_fallback_runs': fallback_runs,
            'network_ready': bool(selected) and not unresolved,
            'field_coupling': header['field_coupling'],
            'coverage': 'provided candidate IDs; not necessarily the full graph',
            'interpretation': 'model threshold candidates; not physiological spikes'}


def graph_config_from_screen(ids, path: Path, template, *, threshold_mv):
    """Bind verified candidates to the exact field configuration and graph.

    A result is returned only when all candidate cells were resolved, at least
    one model transition was selected, and replay cells remain disjoint. The
    source list is built from the complete ledger, never from a partial prefix.
    """
    original = FieldGraphConfig.model_validate(template)
    simulation = original.execution_parameters()['simulation_parameters']
    result = verified_source_cells(ids, path, simulation, threshold_mv=threshold_mv,
                                   graph_hash=original.graph_manifest_sha256)
    if not result['network_ready']:
        raise ValueError('Screen is unresolved or has no stimulated sources')
    if result['field_coupling'] != 'extracellular':
        raise ValueError('Experimental screening coupling is not approved for graph input')
    proposed = original.model_dump(mode='json')
    proposed['source_cells'] = result['selected']
    checked = FieldGraphConfig.model_validate(proposed)
    return {'configuration': checked.model_dump(mode='json'),
            'configuration_sha256': checked.digest(), 'screen_chain_sha256': result['chain_sha256'],
            'screened': result['screened'],
            'coverage': result['coverage'],
            'interpretation': 'paired-model candidate selection; not physiological validation'}


def _screen_one(arguments):
    body, directories, simulation, threshold_mv, field_coupling = arguments
    rows = list(source_screening.screen_source_cells([body], directories, simulation,
                threshold_mv=threshold_mv, **({'field_coupling': field_coupling}
                    if field_coupling != 'extracellular' else {})))
    if len(rows) != 1:
        raise ValueError('Screening worker did not return exactly one record')
    return rows[0]


def _screen_rows(ids, directories, simulation, threshold_mv, workers, field_coupling):
    if workers == 1:
        yield from source_screening.screen_source_cells(ids, directories, simulation,
                   threshold_mv=threshold_mv, **({'field_coupling': field_coupling}
                       if field_coupling != 'extracellular' else {}))
        return
    iterator = iter(ids)
    with ProcessPoolExecutor(max_workers=workers,
                             mp_context=multiprocessing.get_context('spawn')) as executor:
        while batch := list(islice(iterator, workers * 2)):
            jobs = [(body, directories, simulation, threshold_mv, field_coupling) for body in batch]
            yield from executor.map(_screen_one, jobs, chunksize=1)


def compute(ids, directories, output: Path, simulation, *, threshold_mv, graph_hash,
            progress=None, workers=1, field_coupling='extracellular'):
    """Verify any prior prefix and append each paired result in registered order."""
    header = _header(ids, simulation, threshold_mv, graph_hash, workers, field_coupling)
    duration, dt = int(simulation['duration_ms']), simulation.get('dt_ms', .025)
    chain = hashlib.sha256(_canonical(header)).hexdigest()
    completed = 0
    if output.exists():
        with output.open(encoding='utf8') as stream:
            first = stream.readline()
            if not first.endswith('\n') or json.loads(first) != header:
                raise ValueError('Screening file has incompatible provenance')
            for line in stream:
                if not line.endswith('\n'):
                    raise ValueError('Screening file has an incomplete record')
                row = json.loads(line)
                if row.get('kind') == 'footer':
                    if (row != {'kind': 'footer', 'neurons': len(ids), 'chain_sha256': chain}
                            or completed != len(ids) or stream.read(1)):
                        raise ValueError('Invalid screening footer')
                    return completed
                if completed >= len(ids):
                    raise ValueError('Unexpected additional screening record')
                digest = row.pop('chain_sha256', None)
                _check_row(row, ids[completed], duration, dt, field_coupling)
                chain = _step(chain, row)
                if digest != chain:
                    raise ValueError('Screening record checksum mismatch')
                completed += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('a' if output.exists() else 'x', encoding='utf8', newline='\n') as stream:
        if completed == 0 and stream.tell() == 0:
            stream.write(_canonical(header).decode() + '\n')
            stream.flush()
        pending = (_screen_rows(ids[completed:], directories, simulation, threshold_mv, workers,
                                field_coupling)
                   if completed < len(ids) else ())
        for row in pending:
            _check_row(row, ids[completed], duration, dt, field_coupling)
            chain = _step(chain, row)
            stream.write(_canonical({**row, 'chain_sha256': chain}).decode() + '\n')
            stream.flush()
            completed += 1
            if completed % 16 == 0:
                os.fsync(stream.fileno())
            if progress:
                progress(completed, len(ids))
        if completed != len(ids):
            raise ValueError('Screening did not return every candidate')
        stream.write(_canonical({'kind': 'footer', 'neurons': completed,
                                 'chain_sha256': chain}).decode() + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    return completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--morphology-dir', type=Path, action='append', required=True)
    parser.add_argument('--config', type=Path, required=True,
                        help='JSON object with simulation_parameters and threshold_mv')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=1, help='Isolated CPU processes (1–4)')
    parser.add_argument('--field-coupling', choices=('extracellular', 'virtual_current'),
                        default='extracellular', help='Experimental virtual-current screening only')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf8'))
    if not isinstance(config, dict) or set(config) != {'simulation_parameters', 'threshold_mv'}:
        raise ValueError('Invalid screening configuration')
    ids = registered_ids(args.graph / 'ids.npy', args.graph / 'manifest.json')
    count = compute(ids, args.morphology_dir, args.output, config['simulation_parameters'],
                    threshold_mv=config['threshold_mv'], graph_hash=MANIFEST_SHA256,
                    workers=args.workers, field_coupling=args.field_coupling,
                    progress=lambda done, total: print(
                        f'{done}/{total}', file=sys.stderr, flush=True))
    print(json.dumps({'processed': count, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
