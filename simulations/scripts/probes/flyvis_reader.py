"""Read recorded NPY exports using the standard library, without Flyvis or PyTorch."""

import argparse
import array
import ast
import hashlib
import json
import math
import struct
import sys
import zipfile
from pathlib import Path


def read_array(archive, name):
    with archive.open(name + ".npy") as stream:
        assert stream.read(6) == b"\x93NUMPY"
        major, _ = stream.read(2)
        length = struct.unpack(
            "<H" if major == 1 else "<I", stream.read(2 if major == 1 else 4)
        )[0]
        header = ast.literal_eval(stream.read(length).decode("latin1"))
        assert not header["fortran_order"]
        raw = stream.read()
    dtype, shape = header["descr"], header["shape"]
    count = math.prod(shape)
    if dtype in {"<f4", "<f8", "<i8", "<i4"}:
        values = array.array({"<f4": "f", "<f8": "d", "<i8": "q", "<i4": "i"}[dtype])
        values.frombytes(raw)
        if sys.byteorder != "little":
            values.byteswap()
    elif dtype.startswith("<U"):
        size = int(dtype[2:]) * 4
        values = [
            raw[i : i + size].decode("utf-32-le").rstrip("\0")
            for i in range(0, len(raw), size)
        ]
    else:
        raise ValueError("Unreviewed NPY dtype: " + dtype)
    assert len(values) == count
    return values, shape, hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    run = Path(parser.parse_args().run).resolve()
    assert (
        run.parent
        == Path(__file__).resolve().parents[3]
        / "research/.work/simulator-evaluation/SIM-031"
    )
    out = run / "exports"
    result = json.loads((out / "functional.json").read_text())
    assert result["status"] == "passed" and result["nodes"] == 45669
    with zipfile.ZipFile(out / "nodes.npz") as archive:
        ids, shape, _ = read_array(archive, "index")
        names, _, _ = read_array(archive, "cell_type")
        u, _, _ = read_array(archive, "u")
        v, _, _ = read_array(archive, "v")
    assert shape == (45669,) and list(ids) == list(range(45669))
    assert len(set(zip(names, u, v, strict=True))) == 45669
    t4a = [i for i, name in enumerate(names) if name == "T4a"]
    assert t4a
    checked = []
    digests = {}
    for item in result["cases"]:
        path = out / item["file"]
        assert (
            path.parent == out
            and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        )
        with zipfile.ZipFile(path) as archive:
            activity, shape, digest = read_array(archive, "activity")
            inputs, input_shape, input_digest = read_array(archive, "input")
            times, time_shape, _ = read_array(archive, "times_s")
            starts, _, _ = read_array(archive, "input_frame_start_s")
        assert list(shape) == item["shape"] and shape == (1, len(times), 45669)
        assert list(input_shape) == item["input_shape"] and input_shape == (
            1,
            len(times),
            1,
            721,
        )
        assert time_shape == (len(times),) and len(times) > 0
        assert all(math.isfinite(x) for x in activity) and all(
            math.isfinite(x) for x in inputs
        )
        assert (
            digest == item["activity_array_sha256"]
            and input_digest == item["input_array_sha256"]
        )
        dt = item["dt_s"]
        assert all(abs(t - (i + 1) * dt) < 1e-12 for i, t in enumerate(times))
        assert all(abs(t - i * dt) < 1e-12 for i, t in enumerate(starts))
        if item["name"] == "T4a-state-clamp":
            assert item["clamped_nodes"] == t4a
            assert all(
                activity[frame * 45669 + index] == 0
                for frame in range(len(times))
                for index in t4a
            )
        digests[item["name"]] = (digest, input_digest)
        checked.append(
            {"file": path.name, "values": len(activity), "frames": len(times)}
        )
    assert digests["noise-seed-1"] == digests["noise-seed-1-repeat"]
    assert digests["restored-moving-edge"] == digests["native-moving-edge-0"]
    for seed in [2, 3]:
        assert digests[f"noise-seed-{seed}"] != digests["noise-seed-1"]
    value = {
        "status": "passed",
        "imports": "standard library only",
        "nodes": 45669,
        "model_node_identity": "cell_type,u,v (not biological root IDs)",
        "checked": checked,
        "repeat_exact": True,
        "restore_exact": True,
        "post_update_clock": True,
    }
    (out / "independent-readback.json").write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value))


if __name__ == "__main__":
    main()
