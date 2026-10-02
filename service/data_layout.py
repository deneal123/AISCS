"""Single registry of current artifact locations; legacy layouts are explicit."""

from pathlib import Path

GROUPS = {
    "": ("records.json", "aliases.json", "clusters.json", "ST.json", "release-manifest.json"),
    "schema": ("source-record.schema.json", "vocabularies.json"),
    "research": ("dissertation-concept.json", "scientific-contract.json", "novelty-landscape.json"),
    "evidence": (
        "evidence-matrix.json", "human-dataset-matrix.json", "evidence-review-ledger.json",
    ),
    "audits/summary": ("audit-report.json", "completeness-report.json", "validation-log.json"),
    "audits/search": (
        "search-protocol.json", "src07-coverage-ledger-2026-09-25.json",
        "src07-version-recheck-audit.json", "ns15-russian-prior-art-audit.json",
    ),
    "audits/drosophila": (
        "drosophila-connectome-audit.json", "drosophila-nociception-audit.json",
        "ns04-perturbation-model-audit.json", "pa01-s775-s782-citation-pass-2026-09-25.json",
        "runtime-audit.json",
    ),
    "audits/transfer": (
        "synthetic-domain-audit.json", "ns06-prior-art-audit.json",
        "forbidden-transfer-audit-2026-09-25.json",
    ),
    "audits/ecap-scs": (
        "ecap-scs-audit.json", "scs-outcome-audit.json", "ns11-prediction-audit.json",
        "human-ecap-scs-access-audit.json", "ecap-trial-registry-audit.json",
        "pa04-citation-audit-2026-09-25.json",
    ),
}
DATA_PATHS = {name: Path(group) / name for group, names in GROUPS.items() for name in names}


def data_path(root: Path | str, name: str, *, legacy: bool = False) -> Path:
    """Resolve a known logical artifact name without a filesystem fallback."""
    relative = DATA_PATHS[name]
    return Path(root) / (name if legacy else relative)


def current_data_files(root: Path | str) -> list[Path]:
    return [path for name in DATA_PATHS if (path := data_path(root, name)).is_file()]
