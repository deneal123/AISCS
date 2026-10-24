"""Stdlib Linux-проба реальной атомарной private-записи в собственном tmp-каталоге."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def exercise(script):
    with tempfile.TemporaryDirectory(prefix="gpthub-proposal-probe-") as directory:
        root = Path(directory) / "proposals"
        identity, payload = "a" * 32, b'{"fixture":true}'

        def start(data=payload):
            return subprocess.Popen(
                [sys.executable, "-c", script, str(root), identity],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            ), data

        processes = [start() for _ in range(5)]
        results = []
        for process, data in processes:
            output, _ = process.communicate(data, timeout=10)
            assert process.returncode == 0
            results.append(output.strip().decode())
        assert results.count("stored") == 1 and results.count("reused") == 4
        process, _ = start()
        process.communicate(b'{"changed":true}', timeout=10)
        assert process.returncode != 0
        target = root / (identity + ".json")
        assert target.read_bytes() == payload and len(list(root.iterdir())) == 1
        # Even at retention cap, observing a previously committed record is allowed.
        for index in range(63):
            (root / (f"{index:032x}" + ".json")).write_bytes(b"{}")
        process, data = start()
        output, _ = process.communicate(data, timeout=10)
        assert process.returncode == 0 and output.strip() == b"reused"
        # A private path replaced with a link is not a trusted receipt.
        link_id = "b" * 32
        outside = Path(directory) / "outside"
        outside.write_bytes(b"private")
        (root / (link_id + ".json")).symlink_to(outside)
        linked = subprocess.run(
            [sys.executable, "-c", script, str(root), link_id],
            input=b"{}",
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert linked.returncode != 0 and outside.read_bytes() == b"private"
        fifo_id = "c" * 32
        os.mkfifo(root / (fifo_id + ".json"))
        special = subprocess.run(
            [sys.executable, "-c", script, str(root), fifo_id],
            input=b"{}",
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert special.returncode != 0
    return {
        "concurrent_writers": 5,
        "published": 1,
        "reused": 4,
        "conflict_rejected": True,
        "symlink_rejected": True,
        "fifo_rejected": True,
        "fixture_removed": True,
    }


if __name__ == "__main__":
    import runpy

    script = runpy.run_path(sys.argv[1])["STORE_SCRIPT"]
    print(json.dumps(exercise(script)))
