"""Keep the experimental fused Hines kernel aligned with its source solver."""

import ast
from pathlib import Path

import pytest


def _function(path, name):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == name)


@pytest.mark.parametrize(('source_name', 'fused_name'), [
    ('warp_batched', 'warp_batched_recorded'), ('block_cell', 'block_cell_recorded'),
])
def test_fused_kernel_preserves_hines_operations(source_name, fused_name):
    root = (Path(__file__).parents[1] / 'service' / 'infrastructure' / 'stimulation'
            / 'experimental_gpu')
    source = _function(root / 'hines_kernel.py', source_name)
    fused = _function(root / 'fused_observation_kernel.py', fused_name)
    assert [arg.arg for arg in fused.args.args[:len(source.args.args)]] == [
        arg.arg for arg in source.args.args]
    assert [arg.arg for arg in fused.args.args[len(source.args.args):]] == [
        'observation_weights', 'observation_factors', 'selected_nodes', 'selected_counts',
        'signal', 'selected']
    source.name = fused.name = 'kernel'
    fused.args = source.args
    source.body.pop(0)
    fused.body.pop(0)
    source_loop = next(node for node in source.body if isinstance(node, ast.For)
                       and isinstance(node.target, ast.Name) and node.target.id == 'step')
    fused_loop = next(node for node in fused.body if isinstance(node, ast.For)
                      and isinstance(node.target, ast.Name) and node.target.id == 'step')
    start = next(i for i, node in enumerate(fused_loop.body)
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id == 'scratch')
    end = next(i for i in range(start, len(fused_loop.body))
               if isinstance(fused_loop.body[i], ast.For)
               and isinstance(fused_loop.body[i].target, ast.Name)
               and fused_loop.body[i].target.id == 'i')
    del fused_loop.body[start:end]
    assert ast.dump(fused_loop, include_attributes=False) == ast.dump(source_loop,
                                                                     include_attributes=False)
    assert ast.dump(fused, include_attributes=False) == ast.dump(source, include_attributes=False)
