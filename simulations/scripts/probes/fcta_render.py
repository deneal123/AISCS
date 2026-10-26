"""Render the six exact author PDFs, with provenance and no reconstructed figures."""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    run = Path(parser.parse_args().run).resolve()
    root = Path(__file__).resolve().parents[3]
    assert run.parent == root / "research/.work/simulator-evaluation/SIM-030"
    core = json.loads((run / "result.json").read_text())
    assert core["status"] == "reproduced"
    source = run / "source/figures"
    out = run / "exports/figures"
    out.mkdir(exist_ok=True)
    converter = shutil.which("pdftoppm")
    assert converter
    version = subprocess.run(
        [converter, "-v"], capture_output=True, text=True, check=True, timeout=30
    )
    entries = []
    for number in range(1, 7):
        pdf = source / f"figure{number}.pdf"
        before = hashlib.sha256(pdf.read_bytes()).hexdigest()
        started = time.monotonic()
        prefix = out / f"native-figure-{number}"
        command = [converter, "-png", "-r", "120", "-singlefile", str(pdf), str(prefix)]
        process = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=120
        )
        assert process.returncode == 0, process.stderr
        png = prefix.with_suffix(".png")
        content = png.read_bytes()
        assert content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) > 10000
        assert before == hashlib.sha256(pdf.read_bytes()).hexdigest()
        entries.append(
            {
                "number": number,
                "pdf": str(pdf.relative_to(root).as_posix()),
                "pdf_sha256": before,
                "png": png.relative_to(root).as_posix(),
                "png_sha256": hashlib.sha256(content).hexdigest(),
                "command": command,
                "seconds": time.monotonic() - started,
                "stderr": process.stderr,
            }
        )
    result = {
        "status": "passed",
        "scope": "native author figures rasterized, not regenerated from numerical pipeline",
        "attribution": "Stavros Therianos, arXiv:2606.17745, pinned Stavros963/fcta af8e451; figures CC BY 4.0 per README",
        "renderer": converter,
        "renderer_version": version.stdout + version.stderr,
        "entries": entries,
    }
    (run / "figure-render.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("Rendered six original author PDFs at 120 dpi")


if __name__ == "__main__":
    main()
