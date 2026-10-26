"""Run the author's full spectrum calculation without non-exported debug plots."""

import ast
import gc
import hashlib
import json
import runpy
from pathlib import Path

import numpy as np

SOURCE = Path("/work/source/src/mbi_paper/calculate_spectrum_benchtop.py")
OUT = Path("/work/measurement-exports")


def variant(source):
    tree = ast.parse(source)
    start = next(
        i
        for i, n in enumerate(tree.body)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "plot_start" for t in n.targets)
    )
    end = next(
        i
        for i, n in enumerate(tree.body)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "epoched_data" for t in n.targets)
    )
    removed = tree.body[start:end]
    assert any(
        isinstance(n, ast.Expr) and ast.unparse(n).startswith("ax.plot(data)")
        for n in removed
    )
    del tree.body[start:end]
    removed_nested = 0
    for node in tree.body:
        if isinstance(node, ast.For):
            remaining = []
            for child in node.body:
                if (
                    isinstance(child, ast.If)
                    and ast.unparse(child.test) == "idx in (10, 25, 50, 75, 98)"
                ):
                    removed_nested += 1
                else:
                    remaining.append(child)
            node.body = remaining
    assert removed_nested == 1
    # Save the exact computational tree before adding lifetime-only deletions.
    numerical_tree = ast.dump(tree)
    output = []
    inserted = []
    for node in tree.body:
        text = ast.unparse(node)
        if text.startswith("epoched_data ="):
            names = ["d_data", "d_data_abs"]
            deletion = ast.Delete(
                targets=[ast.Name(id=name, ctx=ast.Del()) for name in names]
            )
            output.append(deletion)
            inserted.append(deletion)
        output.append(node)
        if text.startswith("data.index ="):
            deletion = ast.Delete(targets=[ast.Name(id="clinc_df", ctx=ast.Del())])
            output.append(deletion)
            inserted.append(deletion)
        if isinstance(node, ast.For) and "epoched_data[t_on] =" in text:
            deletion = ast.Delete(targets=[ast.Name(id="data", ctx=ast.Del())])
            output.append(deletion)
            inserted.append(deletion)
    assert len(inserted) == 3
    tree.body = output
    assert (
        ast.dump(
            ast.Module(
                body=[node for node in tree.body if node not in inserted],
                type_ignores=[],
            )
        )
        == numerical_tree
    )
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n", {
        "removed_top_level_diagnostic_statements": len(removed),
        "removed_nested_diagnostic_blocks": removed_nested,
        "lifetime_only_deletions": [ast.unparse(node) for node in inserted],
        "calculation_ast_preserved": True,
    }


def main():
    OUT.mkdir(exist_ok=True)
    text = SOURCE.read_text()
    transformed, changes = variant(text)
    target = OUT / "frequency-without-debug-plots.py"
    target.write_text(transformed)
    info = {
        "scope": "explicit memory-adapted variant, all original samples and frequency calculations; not unmodified author reproduction",
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "variant_sha256": hashlib.sha256(transformed.encode()).hexdigest(),
        "changes": changes,
        "source_parquet_sha256": "10032080f4619d7908f5b4dad9ddfad91df397d7f0fac82705423b42d9cfaf84",
    }
    (OUT / "frequency-adaptation.json").write_text(json.dumps(info, indent=2) + "\n")
    module = runpy.run_path(str(target))
    frame = module["rms_df"].copy()
    assert len(frame) == 100 and np.isfinite(frame.to_numpy()).all()
    assert len(module["t_start"]) == len(module["t_end"]) == 100
    frame["t_start_s"] = module["t_start"]
    frame["t_end_s"] = module["t_end"]
    frame.to_csv(OUT / "frequency-values.csv", index=False)
    import matplotlib.pyplot as plt

    plt.close("all")
    del module
    gc.collect()
    info.update(
        status="passed",
        frequencies=100,
        rms_definition="sqrt(median(x**2)); exact author code, not conventional sqrt(mean(x**2))",
        db_definition="10*log10(value/max(value)); exact author code",
        all_input_rows=95555844,
        outputs=[
            "clinc_spectrum.pdf",
            "clinc_spectrum_w_examples.pdf",
            "clinc_spectrum_w_examples.png",
        ],
    )
    (OUT / "frequency-adaptation.json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info), flush=True)


if __name__ == "__main__":
    main()
