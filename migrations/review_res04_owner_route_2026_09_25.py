"""Date the NCT04938245 owner route without treating a promised deposit as data."""

# ruff: noqa: E501 -- exact owner fields and evidence boundaries.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REGISTRY = "https://clinicaltrials.gov/api/v2/studies/NCT04938245"
ZENODO = "https://zenodo.org/api/records?q=NCT04938245"


def updated() -> tuple[dict, str]:
    path = DATA / "human-ecap-scs-access-audit.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    candidate = next(c for c in audit["candidates"] if c["id"] == "HES-UMN-NCT04938245")
    if "owner_route_review_2026_09_25" in candidate or candidate["owner_confirmation_received"]:
        raise ValueError("Owner route changed")
    candidate["owner_route_review_2026_09_25"] = {
        "registry_state": "RECRUITING; last update posted 2025-12-17; primary completion estimated 2026-12-31",
        "ipd_sharing": "YES, planned anonymized and preprocessed Zenodo-or-equivalent deposit for five years; no current accession established",
        "exact_trial_id_zenodo_hits": 0,
        "contact_route": [
            {"name": "David Darrow", "role": "registry central contact", "email": "darro015@umn.edu"},
            {"name": "Alexander Herman", "role": "registry central contact", "email": "herma686@umn.edu"},
        ],
        "draft_request": "docs/data-requests/nct04938245-owner-request-2026-09-25.md",
        "sent": False,
        "decision": "Request draft ready; owner has not confirmed access, reuse terms, waveform/outcome fields or patient linkage.",
        "locators": [
            {"url": REGISTRY, "locator": "protocolSection.statusModule, contactsLocationsModule.centralContacts, ipdSharingStatementModule"},
            {"url": ZENODO, "locator": "hits.total = 0, exact NCT04938245 query on 2026-09-25"},
        ],
    }
    audit["meta"]["audited_at"] = "2026-09-25"
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    old = "Ни один набор не признан доступным без подтверждения владельца состава и связности данных."
    if todo.count(old) != 1:
        raise ValueError("RES-04 TODO note changed")
    todo = todo.replace(old, old + " Для NCT04938245 сверены действующие контакты реестра и отсутствие Zenodo-записи по точному ID на 25.09; подготовлен, но не отправлен запрос владельцу в `docs/data-requests/nct04938245-owner-request-2026-09-25.md`. Подтверждения состава, linkage, consent и DUA пока нет.")
    return audit, todo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit, todo = updated()
    if not args.apply:
        print("Dry run: owner route documented; RES-04 remains open")
        return
    snapshot = snapshot_repository(DATA, label="pre-res04-owner-route-review")
    atomic_write_json(DATA / "human-ecap-scs-access-audit.json", audit)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    print(f"Recorded owner route; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
