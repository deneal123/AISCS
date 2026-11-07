"""Prepare a graph request only from a complete, resolved full-graph screen."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_full_morphology import MANIFEST_SHA256, registered_ids  # noqa: E402
from scripts.screen_stim_sources import graph_config_from_screen  # noqa: E402
from service.domain.contracts.field_graph_contract import FieldGraphConfig  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--screen', type=Path, required=True)
    parser.add_argument('--template', type=Path, required=True,
                        help='Existing field-graph configuration used as template')
    parser.add_argument('--threshold-mv', type=float, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ids = registered_ids(args.graph / 'ids.npy', args.graph / 'manifest.json')
    template = json.loads(args.template.read_text(encoding='utf8'))
    if FieldGraphConfig.model_validate(template).graph_manifest_sha256 != MANIFEST_SHA256:
        raise ValueError('Template graph does not match the registered graph')
    result = graph_config_from_screen(ids, args.screen, template, threshold_mv=args.threshold_mv)
    result['coverage'] = 'all registered graph IDs; paired model screen'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        stream.write('\n')
    print(json.dumps({'screened': result['screened'],
                      'sources': len(result['configuration']['source_cells']),
                      'configuration_sha256': result['configuration_sha256']}))


if __name__ == '__main__':
    main()
