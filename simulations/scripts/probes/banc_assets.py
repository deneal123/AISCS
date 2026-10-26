"""Acquire only the pinned BANC metadata and its declared v888/v2 edge product."""

import base64
import hashlib
import subprocess
import urllib.request
from datetime import UTC, datetime

from inventory import REGISTRY, ROOT, load, save
from simctl import checked_work

META = "data/meta/banc_888_meta_20260521.parquet"
BASE = (
    "https://storage.googleapis.com/"
    "lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/banc_888/"
)
EDGE = "banc_888_edgelist_simple_v2.feather"


def restore_blob(base, commit, name, target):
    line = subprocess.check_output(
        ["git", "ls-tree", "--long", commit, "--", name], cwd=base, text=True
    ).strip()
    metadata, found = line.split("\t", 1)
    mode, kind, oid, size = metadata.split()
    if found != name or kind != "blob" or mode != "100644":
        raise ValueError("Unexpected pinned BANC entry: " + name)
    content = subprocess.check_output(
        ["git", "cat-file", "blob", oid], cwd=base, timeout=90
    )
    actual = hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\0" + content
    ).hexdigest()
    if actual != oid or len(content) != int(size):
        raise ValueError("BANC Git blob mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    git_size = len(content)
    eol_conversion = False
    if target.exists():
        existing = target.read_bytes()
        if existing != content:
            if existing.replace(b"\r\n", b"\n") != content:
                raise ValueError("Existing pinned BANC checkout differs from Git blob")
            eol_conversion = True
        content = existing  # Preserve the attested checkout's original bytes.
    else:
        target.write_bytes(content)
    return {
        "git_path": name,
        "git_blob": oid,
        "bytes": len(content),
        "git_bytes": git_size,
        "checkout_eol_conversion": eol_conversion,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def download(url, target):
    failures = []
    for attempt in (1, 2):
        temporary = target.with_suffix(target.suffix + ".part")
        try:
            sha = hashlib.sha256()
            md5 = hashlib.md5()
            count = 0
            target.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url, timeout=90) as response:
                headers = response.headers
                with temporary.open("wb") as stream:
                    while block := response.read(1024**2):
                        count += len(block)
                        if count > 1024**3:
                            raise ValueError("Unexpected BANC product size")
                        sha.update(block)
                        md5.update(block)
                        stream.write(block)
            if count != int(headers["Content-Length"]):
                raise ValueError("Truncated BANC download")
            hash_headers = (
                headers.get_all("x-goog-hash", [])
                if hasattr(headers, "get_all")
                else [headers.get("x-goog-hash", "")]
            )
            expected = next(
                (
                    x.strip()[4:]
                    for x in ",".join(hash_headers).split(",")
                    if x.strip().startswith("md5=")
                ),
                None,
            )
            if not expected or base64.b64encode(md5.digest()).decode() != expected:
                raise ValueError("BANC primary MD5 absent or mismatched")
            with temporary.open("rb") as stream:
                if stream.read(6) != b"ARROW1":
                    raise ValueError("BANC product is not Arrow IPC")
                stream.seek(-6, 2)
                if stream.read() != b"ARROW1":
                    raise ValueError("Incomplete Arrow IPC footer")
            temporary.replace(target)
            return {
                "url": url,
                "bytes": count,
                "sha256": sha.hexdigest(),
                "upstream_md5": expected,
                "last_modified": headers.get("Last-Modified"),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "attempt": attempt,
                "failed_attempts": failures,
            }
        except (OSError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            failures.append(str(exc))
    raise ValueError("BANC public route failed twice: " + repr(failures))


def hydrate(run):
    run = checked_work(run)
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-011")
    base = ROOT / row["path"]
    receipt = {
        "commit": row["commit"],
        "materialization": 888,
        "synapse_product": "v2; size >=5 upstream",
        "inputs": [],
    }
    for name in (
        META,
        "DESCRIPTION",
        "data/meta/README.md",
        "manuscript/print/banc_data_locations.md",
    ):
        item = restore_blob(base, row["commit"], name, run / "source" / name)
        item["file"] = "source/" + name
        receipt["inputs"].append(item)
    item = download(BASE + EDGE, run / "inputs" / EDGE)
    item["file"] = "inputs/" + EDGE
    receipt["inputs"].append(item)
    save(run / "banc-inputs.json", receipt)
    print("BANC v888 inputs verified", flush=True)
