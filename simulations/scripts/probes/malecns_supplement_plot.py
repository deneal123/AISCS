"""Visualize two pinned published QC tables with no numerical-model claims."""

import csv
import hashlib
import html
import json
import math
import sys
from pathlib import Path


def main():
    run = Path(sys.argv[1]).resolve()
    manifest = json.loads((run / "pinned-supplements.json").read_text())
    out = run / "exports/malecns-notebook"
    fragments = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720">',
        '<rect width="1200" height="720" fill="white"/>',
        '<g font-family="Arial,sans-serif" fill="#20252a">',
        '<text x="600" y="38" text-anchor="middle" font-size="25">MaleCNS v1.0: published synapse quality by region</text>',
    ]
    provenance = []
    for panel, (kind, label, color) in enumerate(
        (
            ("connection", "Synapse connections", "#365b85"),
            ("tbar", "T-bars", "#8b5792"),
        )
    ):
        name = f"supplemental_data/male-cns-v1.0-synapse-{kind}-precision-recall-by-roi.csv"
        item = next(x for x in manifest["files"] if x["path"] == name)
        path = run / "source" / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == item["sha256"]
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 81 and len({x["roi"] for x in rows}) == 81
        left, top, size = 85 + panel * 590, 120, 440
        fragments.append(
            f'<text x="{left + size / 2}" y="90" text-anchor="middle" font-size="22">{label}: 81 regions</text>'
        )
        for tick in (0, 25, 50, 75, 100):
            x, y = left + size * tick / 100, top + size * (1 - tick / 100)
            fragments.extend(
                (
                    f'<path d="M{x},{top} v{size} M{left},{y} h{size}" fill="none" stroke="#d9dfe4"/>',
                    f'<text x="{x}" y="{top + size + 27}" text-anchor="middle" font-size="17">{tick}</text>',
                    f'<text x="{left - 12}" y="{y + 6}" text-anchor="end" font-size="17">{tick}</text>',
                )
            )
        for row in rows:
            recall, precision = float(row["recall"]), float(row["precision"])
            assert all(math.isfinite(v) and 0 <= v <= 1 for v in (recall, precision))
            title = html.escape(f"{row['roi']}: recall={recall}, precision={precision}")
            fragments.append(
                f'<circle cx="{left + size * recall}" cy="{top + size * (1 - precision)}" r="4.5" fill="{color}" fill-opacity="0.6"><title>{title}</title></circle>'
            )
        fragments.extend(
            (
                f'<text x="{left + size / 2}" y="620" text-anchor="middle" font-size="20">Recall, %</text>',
                f'<text transform="translate({left - 58},340) rotate(-90)" text-anchor="middle" font-size="20">Precision, %</text>',
            )
        )
        provenance.append({"source": name, "sha256": actual, "rows": len(rows)})
    fragments.extend(
        (
            '<text x="600" y="667" text-anchor="middle" font-size="18">Reported author metrics; equal-size points. Hover over SVG points for region names.</text>',
            '<text x="600" y="696" text-anchor="middle" font-size="18">Separate v1.0 supplements; not v0.9 notebook results or an independent biological validation.</text>',
            "</g></svg>",
        )
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "published-synapse-quality.svg").write_text(
        "\n".join(fragments) + "\n", encoding="utf-8"
    )
    (out / "visual-provenance.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "inputs": provenance,
                "scope": "Display of published author quality metrics only; no new simulation or independent estimation",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
