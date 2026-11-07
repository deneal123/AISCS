"""Audit predicted MANC matches without promoting them to functional labels.

Inputs are a downloaded author notebook and the unmodified MaleCNS annotation
table. This is an evidence report, not a cell-identity or pathway validator.
"""

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow.feather as feather


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def notebook_ids(path):
    notebook = json.loads(path.read_text(encoding='utf-8'))
    matches = []
    for cell in notebook['cells']:
        source = ''.join(cell.get('source', []))
        if 'md_4_neurons' not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in tree.body:
            if (isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == 'md_4_neurons'
                    for target in node.targets)):
                matches.append(ast.literal_eval(node.value))
    if (len(matches) != 1 or not isinstance(matches[0], list) or not matches[0]
            or any(type(value) is not int or value <= 0 for value in matches[0])
            or len(set(matches[0])) != len(matches[0])):
        raise ValueError('Expected one unique, nonempty md_4_neurons ID list')
    return matches[0]


def audit(notebook, annotations):
    ids = notebook_ids(notebook)
    columns = ['bodyId', 'mancBodyid', 'mancType', 'mancGroup', 'matchingNotes',
               'type', 'superclass', 'class', 'entryNerve']
    table = feather.read_table(annotations, columns=columns)
    candidates = []
    for row in table.to_pylist():
        predicted = row['mancBodyid']
        if predicted is not None and predicted in ids:
            row['mancBodyid'] = int(predicted)
            candidates.append(row)
    candidates.sort(key=lambda row: (row['mancBodyid'], row['bodyId']))
    multiplicity = Counter(row['mancBodyid'] for row in candidates)
    return {
        'interpretation': ('Predicted cross-dataset candidates, '
                           'not validated identities or function.'),
        'source_notebook_sha256': sha256(notebook),
        'male_cns_annotations_sha256': sha256(annotations),
        'source_manc_ids': ids,
        'missing_manc_ids': sorted(set(ids) - set(multiplicity)),
        'ambiguous_manc_ids': sorted(key for key, count in multiplicity.items() if count > 1),
        'candidates': candidates,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notebook', type=Path, required=True)
    parser.add_argument('--annotations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.notebook, args.annotations)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')


if __name__ == '__main__':
    main()
