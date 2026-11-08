"""Run a field-proxy network from an audited complete field summary.

This is an experimental offline tool, not a physical ECAP or validated response.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.application.field.field_proxy_execution import execute_field_proxy  # noqa: E402
from service.infrastructure.connectome.neighbors import registered_graph  # noqa: E402
from service.infrastructure.stimulation.field_summary_verified import (
    verified_descriptors,  # noqa: E402,F401
)
from service.settings import morphology_directories  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--field', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gain', type=float, required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--waveform', type=Path, required=True,
                        help='JSON list of relative current multipliers, one per millisecond')
    parser.add_argument('--allow-partial-geometry', action='store_true')
    parser.add_argument('--allow-missing-curvature', action='store_true')
    parser.add_argument('--allow-contact-exclusion', action='store_true')
    parser.add_argument('--compute-field', action='store_true',
                        help='Compute or resume the field for these exact contacts')
    parser.add_argument('--capture-delta', action='store_true',
                        help='Capture per-cell differences against a matched no-field control')
    parser.add_argument('--field-workers', type=int, default=1)
    parser.add_argument('--field-backend', choices=('cpu', 'gpu'), default='cpu',
                        help='Field operator only; GPU requires --compute-field')
    parser.add_argument('--geometry-cache', type=Path)
    parser.add_argument('--geometry-cache-sha256')
    parser.add_argument('--source-index', type=Path)
    parser.add_argument('--source-audit', type=Path)
    parser.add_argument('--source-um', type=float, nargs=3, required=True)
    parser.add_argument('--return-um', type=float, nargs=3, required=True)
    parser.add_argument('--current-na', type=float, required=True)
    parser.add_argument('--conductivity-s-m', type=float, required=True)
    parser.add_argument('--clearance-um', type=float, required=True)
    args = parser.parse_args()
    cache_values = (args.geometry_cache, args.geometry_cache_sha256,
                    args.source_index, args.source_audit)
    if any(value is not None for value in cache_values) and (
        any(value is None for value in cache_values) or args.field_backend != 'gpu'
        or not args.compute_field
    ):
        parser.error('Geometry cache requires GPU computation and all four cache arguments')
    geometry_cache = (None if args.geometry_cache is None else {
        'directory': args.geometry_cache,
        'expected_manifest_sha256': args.geometry_cache_sha256,
        'source_index': args.source_index, 'source_audit': args.source_audit,
    })
    if args.output.exists():
        raise ValueError('Output already exists')
    graph = registered_graph()
    configuration = {'source_um': args.source_um, 'return_um': args.return_um,
                     'current_na': args.current_na, 'conductivity_s_m': args.conductivity_s_m,
                     'clearance_um': args.clearance_um}
    waveform = json.loads(args.waveform.read_text(encoding='utf8'))
    execute_field_proxy(graph, morphology_directories(), field_path=args.field, output=args.output,
        configuration=configuration, gain=args.gain, seed=args.seed, waveform=waveform,
        compute_field=args.compute_field, allow_partial_geometry=args.allow_partial_geometry,
        allow_missing_curvature=args.allow_missing_curvature,
        allow_contact_exclusion=args.allow_contact_exclusion, capture_delta=args.capture_delta,
        field_workers=args.field_workers, field_backend=args.field_backend,
        geometry_cache=geometry_cache)

if __name__ == '__main__':
    main()
