"""Plot measured convergent responses without importing the source simulator."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    run = Path(parser.parse_args().run).resolve()
    assert (
        run.parent
        == Path(__file__).resolve().parents[3]
        / "research/.work/simulator-evaluation/SIM-029"
    )
    out = run / "exports"
    data = json.loads((out / "convergent-propagation.json").read_text())
    assert data["status"] == "passed"
    top = max(1.1, data["intact"]["max_target_potential"] * 1.1)
    layers = []
    for key, color, label in [
        ("intact", "#176294", "Connected graph"),
        ("zero_weights", "#a05b27", "Weights = 0"),
    ]:
        series = data[key]["series"]
        points = " ".join(
            f"{80 + x['tick'] * 6:.2f},{325 - x['target_potential'] * 215 / top:.2f}"
            for x in series
        )
        layers.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>'
        )
        layers.append(
            f'<text x="{100 if key == "intact" else 450}" y="380" fill="{color}">{label}</text>'
        )
    for x in data["intact"]["series"]:
        if x["target_event"]:
            position = 80 + x["tick"] * 6
            layers.append(
                f'<path d="M{position} 450v40" stroke="#176294" stroke-width="2"/>'
            )
    for tick in [0, 40, 80, 120, 160]:
        layers.append(
            f'<text x="{80 + tick * 6}" y="350" text-anchor="middle">{tick}</text>'
        )
    for value in [0, 0.5, 1]:
        y = 325 - value * 215 / top
        layers.append(
            f'<text x="68" y="{y + 6:.2f}" text-anchor="end">{value:g}</text>'
        )
    y = 325 - 215 / top
    layers.append(
        f'<path d="M80 {y:.2f}H1040" stroke="#888" stroke-dasharray="5 5" fill="none"/><text x="1045" y="{y + 6:.2f}">1</text>'
    )
    target = data["target_worker_index"]
    title = f"Recorded propagation to worker neuron {target}"
    note = f"256 stimulated inputs; target events: {data['intact']['target_events']} with connections, {data['zero_weights']['target_events']} without"
    text = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="610" viewBox="0 0 1120 610"><rect width="1120" height="610" fill="white"/><g font-family="Arial" font-size="20" fill="#222"><text x="65" y="40">{title}</text><text x="65" y="75">{note}</text><text x="80" y="105">Normalized model state before threshold/reset</text><path d="M80 115V325H1040" fill="none" stroke="#222"/>{"".join(layers)}<text x="80" y="430">Threshold events at the unstimulated target</text><path d="M80 495H1040" stroke="#222"/><text x="80" y="535">Model ticks; neither milliseconds nor physical membrane voltage</text><text x="80" y="575">Diagnostic convergence experiment; not a natural stimulus or biological validation</text></g></svg>"""
    (out / "recorded-propagation.svg").write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
