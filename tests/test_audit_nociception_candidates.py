import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_nociception_candidates.py'
spec = importlib.util.spec_from_file_location('audit_nociception_candidates', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_reports_missing_and_ambiguous_without_assigning_function(tmp_path):
    notebook = tmp_path / 'figure4.ipynb'
    notebook.write_text(json.dumps({'cells': [{'source': ['md_4_neurons = [1, 2, 3]']}]}))
    annotations = tmp_path / 'neurons.feather'
    feather.write_feather(pa.table({
        'bodyId': [20, 10, 30], 'mancBodyid': [1., 1., 2.],
        'mancType': ['a', 'a', 'b'], 'mancGroup': [None, None, None],
        'matchingNotes': [None, None, None], 'type': ['a', 'a', 'b'],
        'superclass': ['vnc_sensory'] * 3, 'class': ['unknown_sensory'] * 3,
        'entryNerve': ['AbN2'] * 3,
    }), annotations)
    report = module.audit(notebook, annotations)
    assert report['missing_manc_ids'] == [3]
    assert report['ambiguous_manc_ids'] == [1]
    assert [row['bodyId'] for row in report['candidates']] == [10, 20, 30]
    assert 'not validated' in report['interpretation']
    assert len(report['source_notebook_sha256']) == 64


@pytest.mark.parametrize('source', ['md_4_neurons = [1, 1]', 'md_4_neurons = []',
                                    'md_4_neurons = ["1"]'])
def test_rejects_invalid_source_list(tmp_path, source):
    notebook = tmp_path / 'figure4.ipynb'
    notebook.write_text(json.dumps({'cells': [{'source': [source]}]}))
    with pytest.raises(ValueError):
        module.notebook_ids(notebook)
