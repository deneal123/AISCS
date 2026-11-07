"""Map recorded simulator checks to local receipt identities, without copying receipts."""

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
inventory_path = HERE / "simulator-inventory.json"
manifest_path = HERE / "simulator-receipts-manifest.json"
inventory = json.loads(inventory_path.read_text(encoding="utf-8"))["candidates"]
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
receipts = {item["path"]: item for item in manifest["receipts"]}
if len(inventory) != 32 or len(receipts) != len(manifest["receipts"]):
    raise ValueError("Unexpected inventory size or duplicate receipt paths")

lines = [
    "# Указатель локальных квитанций испытаний",
    "",
    "Рабочее приложение к PUB-002: сопоставление отметок реестра с файлами исходных "
    "испытаний. Локальные пути не являются общедоступными ссылками; перед подачей "
    "необходимы проверка прав распространения и постоянный доступный читателю архив. "
    "Хеш удостоверяет идентичность файла, но не правильность его содержимого. "
    "В одном пункте могут быть перечислены как неудачные, так и последующие попытки; "
    "каждую квитанцию следует читать с учётом её сценария и даты.",
    "",
    f"Срез манифеста: {manifest['created_on']}; SHA-256 манифеста: "
    f"`{hashlib.sha256(manifest_path.read_bytes()).hexdigest()}`.",
    "",
]
labels = {
    "environment": "Окружение",
    "software": "Программные проверки",
    "smoke": "Минимальный запуск",
    "functional": "Функциональный сценарий",
    "reproducibility": "Повторяемость",
}
count = 0
for item in inventory:
    lines.extend([f"## {item['id']} — {item['repository']}", ""])
    for check, label in labels.items():
        links = []
        for path in item.get("evidence", {}).get(check, []):
            if not path.startswith("research/.work/"):
                continue
            receipt = receipts.get(path)
            if not receipt or not receipt.get("available") or not receipt.get("sha256"):
                raise ValueError(f"Missing receipt identity: {item['id']} {check} {path}")
            link = quote("../../../../" + path, safe="/._-")
            links.append(f"[{path}]({link}) — SHA-256 `{receipt['sha256']}`")
            count += 1
        state = item["checks"].get(check, "не указано")
        lines.append(f"- **{label} — {state}.**")
        if links:
            lines.extend(f"  - {link}" for link in links)
        else:
            lines.append("  - Локальная квитанция в выбранном реестре не указана.")
    lines.append("")

target = HERE / "receipt-index.md"
target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
print(f"{len(inventory)} кандидата, {count} ссылок на локальные квитанции")
