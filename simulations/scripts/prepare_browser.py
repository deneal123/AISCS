"""Install the pinned browser driver in ignored work storage; use the system browser."""

import json
import os
import shutil
import subprocess

from paths import ROOT, WORK


def main():
    source = ROOT / "simulations/environments/browser-tools"
    destination = (WORK / "browser-tools").resolve()
    if not destination.is_relative_to(WORK.resolve()):
        raise ValueError("Browser tools must remain inside simulation work storage")
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copyfile(source / name, destination / name)
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("Node.js/npm is required for browser checks")
    subprocess.run(
        [
            npm,
            "ci",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--cache",
            str(WORK / "npm-cache"),
        ],
        cwd=destination,
        env={**os.environ, "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"},
        check=True,
    )
    print(json.dumps({"tools": str(destination), "browser_downloaded": False}))


if __name__ == "__main__":
    main()
