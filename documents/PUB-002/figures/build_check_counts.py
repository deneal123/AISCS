# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib>=3.9,<4"]
# ///
"""Draw the registered check counts, not a comparison of model quality."""

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
manifest = json.loads(
    (HERE.parent / "simulator-receipts-manifest.json").read_text(encoding="utf-8")
)
counts = manifest["passed_by_check"]
total = manifest["candidate_count"]
keys = ["environment", "software", "smoke", "functional", "reproducibility"]
labels = [
    "Подготовка окружения",
    "Программные проверки",
    "Минимальный запуск",
    "Функциональный сценарий",
    "Проверка повторяемости",
]
assert total == 32 and [counts[key] for key in keys] == [31, 27, 30, 24, 31]
font = Path("C:/Windows/Fonts/times.ttf")
if font.exists():
    font_manager.fontManager.addfont(str(font))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font)).get_name()
else:
    plt.rcParams["font.family"] = "DejaVu Serif"
plt.rcParams.update({"font.size": 11, "pdf.fonttype": 42, "svg.fonttype": "none"})
fig, ax = plt.subplots(figsize=(6.45, 2.9), layout="constrained")
y = np.arange(len(keys))
ax.barh(y, [total] * len(keys), height=0.48, color="#edf0f3", zorder=0)
ax.barh(y, [counts[key] for key in keys], height=0.48, color="#426783", zorder=2)
for i, key in enumerate(keys):
    ax.text(total + 0.6, i, f"{counts[key]}/{total}", va="center", fontsize=11)
ax.set_yticks(y, labels)
ax.invert_yaxis()
ax.set_xlim(0, 36)
ax.set_xticks([0, 8, 16, 24, 32])
ax.set_xlabel("Число репозиториев")
ax.tick_params(axis="both", length=0, pad=6)
ax.grid(axis="x", color="#d6dbe0", linewidth=0.6, zorder=1)
for spine in ax.spines.values():
    spine.set_visible(False)
for ext in ("pdf", "svg", "png"):
    fig.savefig(HERE / f"tool-check-counts.{ext}", dpi=400, facecolor="white")
plt.close(fig)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


provenance = {
    "input_sha256": digest(HERE.parent / "simulator-receipts-manifest.json"),
    "output_sha256": {
        f"tool-check-counts.{ext}": digest(HERE / f"tool-check-counts.{ext}")
        for ext in ("pdf", "svg", "png")
    },
    "counts": {key: counts[key] for key in keys},
    "candidate_count": total,
}
(HERE / "tool-check-counts.provenance.json").write_text(
    json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
)
