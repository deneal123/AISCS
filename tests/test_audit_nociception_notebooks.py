import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import audit_nociception_notebooks  # noqa: E402


def test_compares_lists_and_declared_exclusions_without_executing(tmp_path):
    one, two = tmp_path / 'one.ipynb', tmp_path / 'two.ipynb'
    one.write_text(json.dumps({'cells': [{'source': ['md_4_neurons = [1, 2]']}]}))
    two.write_text(json.dumps({'cells': [{'source': [
        'md_4_neurons = [1, 2, 3]\n', 'exclude = [3]\n', 'raise RuntimeError()']}]}))
    report = audit_nociception_notebooks.audit(one, two)
    assert report['only_figure5'] == [3]
    assert report['figure5_declared_exclusions'] == [3]
    assert report['figure5_declared_selection'] == [1, 2]


def test_rejects_ambiguous_exclusion_lists(tmp_path):
    path = tmp_path / 'bad.ipynb'
    path.write_text(json.dumps({'cells': [{'source': ['exclude=[1]\nexclude=[2]']}]}))
    with pytest.raises(ValueError, match='exclude'):
        audit_nociception_notebooks.named_list(path, 'exclude')
