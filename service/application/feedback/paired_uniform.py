"""Paired fixed-schedule GPU replays with a shared verified uniform grid."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np

from service.infrastructure.stimulation.experimental_gpu.refined_population import (
    uniform_cell_transform,
)
from service.infrastructure.stimulation.feedback.discretization import (
    prepare_uniform_feedback_replays,
)

from .population_bulk_replay import replay_verified_feedback_to_archive


def replay_paired_uniform(metadata, stimulus, rate_table, *, conditions, index, directories,
                          policy, morphology_sha256, metadata_factory, replay_options,
                          output_directory):
    """Stage both conditions on identical grids and publish only as one directory.

    This is a fixed-schedule replay, not a converged network. The caller must
    restart both conditions whenever the shared grid changes.
    """
    destination = Path(output_directory)
    if (not isinstance(replay_options, dict) or 'cell_transform' in replay_options
            or not callable(metadata_factory) or not destination.parent.is_dir()
            or destination.exists() or destination.is_symlink()):
        raise ValueError('Invalid paired population replay options')
    values = np.asarray(stimulus, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError('Invalid paired population stimulus')
    prepared = prepare_uniform_feedback_replays(conditions, index, directories, **policy)
    transform = uniform_cell_transform(prepared['nseg_by_body'], directories,
        replay_options['params'], capture_original=metadata_factory)
    with tempfile.TemporaryDirectory(prefix='.paired-grid-', dir=destination.parent) as scratch:
        staged = Path(scratch) / 'result'
        staged.mkdir()
        results = {}
        for name, signal in (('control', np.zeros_like(values)), ('stimulated', values)):
            item = prepared['conditions'][name]
            results[name] = replay_verified_feedback_to_archive(metadata, signal, rate_table,
                schedule=item['schedule'], schedule_sha256=item['sha256'],
                morphology_sha256=morphology_sha256, event_path=staged / f'{name}.jsonl',
                metadata_factory=metadata_factory, cell_transform=transform, **replay_options)
        time = np.asarray(replay_options['time_ms'], dtype=float)
        traces = {name: np.asarray(result['neural_uv'], dtype=float)
                  for name, result in results.items()}
        if (time.shape != values.shape or not np.isfinite(time).all()
                or any(trace.shape != values.shape or not np.isfinite(trace).all()
                       for trace in traces.values())):
            raise ValueError('Invalid paired population recording')
        for name, result in results.items():
            with (staged / f'{name}.jsonl').open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != result['event_sha256']:
                    raise ValueError('Paired population archive digest mismatch')
        np.savez_compressed(staged / 'signals.npz', time_ms=time, stimulus=values,
                            control_uv=traces['control'], stimulated_uv=traces['stimulated'])
        audit = {'grid': prepared['nseg_by_body'], 'audit': prepared['audit'],
                 'conditions': {name: {key: item[key] for key in ('sha256', 'original_sha256')}
                                for name, item in prepared['conditions'].items()}}
        (staged / 'grid-audit.json').write_text(
            json.dumps(audit, sort_keys=True, allow_nan=False) + '\n', encoding='utf8')
        files = {}
        for path in staged.iterdir():
            with path.open('rb') as stream:
                files[path.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        (staged / 'manifest.json').write_text(json.dumps({
            'kind': 'paired-fixed-feedback', 'file_hashes': files,
            'interpretation': 'fixed schedule replay; not converged or biologically validated',
        }, sort_keys=True) + '\n', encoding='utf8')
        os.rename(staged, destination)
    return {'conditions': results, 'grid': prepared['nseg_by_body'],
            'restart_required': prepared['restart_required'], 'audit': prepared['audit'],
            'interpretation': 'paired fixed schedules; not converged or biologically validated'}
