"""Compare author notebook inputs and declared exclusions without executing code."""

import argparse
import ast
import json
from pathlib import Path

from audit_nociception_candidates import notebook_ids, sha256


def named_list(path, name):
    notebook = json.loads(path.read_text(encoding='utf-8'))
    found = []
    for cell in notebook['cells']:
        try:
            tree = ast.parse(''.join(cell.get('source', [])))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets
            ):
                found.append(ast.literal_eval(node.value))
    if (len(found) != 1 or not isinstance(found[0], list)
            or any(type(item) is not int or item <= 0 for item in found[0])
            or len(set(found[0])) != len(found[0])):
        raise ValueError(f'Expected one unique integer list: {name}')
    return found[0]


def audit(figure4, figure5):
    first, second = notebook_ids(figure4), notebook_ids(figure5)
    excluded = named_list(figure5, 'exclude')
    return {'figure4_sha256': sha256(figure4), 'figure5_sha256': sha256(figure5),
            'figure4_count': len(first), 'figure5_count': len(second),
            'only_figure4': sorted(set(first) - set(second)),
            'only_figure5': sorted(set(second) - set(first)),
            'figure5_declared_exclusions': sorted(excluded),
            'figure5_declared_selection': sorted(set(second) - set(excluded)),
            'interpretation': ('Declared exclusions do not establish executed filter behavior '
                               'or experimental cell identity.')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--figure4', type=Path, required=True)
    parser.add_argument('--figure5', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(audit(args.figure4, args.figure5), indent=2) + '\n',
                           encoding='utf-8')


if __name__ == '__main__':
    main()
