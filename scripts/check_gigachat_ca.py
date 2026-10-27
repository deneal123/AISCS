"""Verify the vendored public GigaChat root without network access."""

from __future__ import annotations

import hashlib
import ssl
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CERT = ROOT / "infra" / "certs" / "gigachat-ca.pem"
SOURCE = ROOT / "infra" / "certs" / "gigachat-ca.source"


def _metadata() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def main() -> None:
    metadata = _metadata()
    actual = hashlib.sha256(CERT.read_bytes()).hexdigest()
    if actual != metadata.get("sha256"):
        raise SystemExit("GigaChat CA checksum mismatch")
    certificate = ssl._ssl._test_decode_cert(str(CERT))  # type: ignore[attr-defined]  # noqa: SLF001
    not_after = str(certificate.get("notAfter") or "")
    if ssl.cert_time_to_seconds(not_after) <= time.time():
        raise SystemExit("GigaChat CA is expired")
    ssl.create_default_context(cafile=str(CERT))
    if not metadata.get("source", "").startswith("https://"):
        raise SystemExit("GigaChat CA source is not HTTPS")
    print("GigaChat CA: OK")


if __name__ == "__main__":
    main()
