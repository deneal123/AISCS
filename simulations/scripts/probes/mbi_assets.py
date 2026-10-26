"""Materialize verified OSF recordings without modifying the pinned sidecar."""

import ast
import hashlib
import shutil
import subprocess

from inventory import REGISTRY, ROOT, load, save
from simctl import checked_work

COMMIT = "604d17fe1d39a6618fd8f26694922a823aeed8c8"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def headless(text):
    """Replace only the explicitly requested GUI backend, preserving the AST."""
    before = ast.parse(text)
    changes = 0
    for node in ast.walk(before):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "mpl"
            and node.func.attr == "use"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "tkagg"
        ):
            node.args[0].value = "Agg"
            changes += 1
    edited = text.replace("mpl.use('tkagg')", "mpl.use('Agg')")
    if ast.dump(before) != ast.dump(ast.parse(edited)):
        raise ValueError("Unexpected change beyond the explicit TkAgg backend")
    return edited, changes


def copy_verified(primary, target, size, sha256):
    primary, target = checked_work(primary), checked_work(target)
    if primary.stat().st_size != size or digest(primary) != sha256:
        raise ValueError("OSF primary identity differs: " + primary.name)
    if target.exists():
        if target.stat().st_size != size or digest(target) != sha256:
            raise ValueError("Preserving changed run input: " + str(target))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(primary, target)
        if digest(target) != sha256:
            raise ValueError("OSF run copy differs")


def hydrate(run):
    run = checked_work(run)
    if run.parent.name != "SIM-025":
        raise ValueError("MBI recordings require an owned SIM-025 run")
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-025")
    if row["commit"] != COMMIT:
        raise ValueError("Unreviewed MBI commit")
    from probes.mbi_download import acquire

    ledger = acquire()
    if not ledger["complete"] or ledger["errors"] or len(ledger["files"]) != 72:
        raise ValueError("OSF acquisition has not completed with 72 verified files")
    for item in ledger["files"]:
        relative = item["path"]
        if item["status"] != "verified":
            raise ValueError("Unverified OSF input")
        copy_verified(
            ROOT / item["primary"],
            run / "source/data" / relative,
            item["bytes"],
            item["sha256"],
        )
    changes = []
    sidecar = ROOT / row["path"]
    for path in sorted((run / "source/src/mbi_paper").glob("*.py")):
        relative = path.relative_to(run / "source").as_posix()
        original = subprocess.check_output(
            ["git", "show", COMMIT + ":" + relative], cwd=sidecar, timeout=30
        )
        text = path.read_text(encoding="utf-8")
        if text != original.decode().replace("\r\n", "\n"):
            raise ValueError("Working source differs before backend adaptation")
        edited, count = headless(text)
        if count:
            before = digest(path)
            path.write_text(edited, encoding="utf-8", newline="\n")
            changes.append(
                {
                    "file": relative,
                    "before_sha256": before,
                    "after_sha256": digest(path),
                    "changes": count,
                    "scope": "TkAgg to Agg; identical AST except backend constant",
                }
            )
    (run / "source/figures").mkdir(exist_ok=True)
    save(run / "mbi-inputs.json", ledger)
    save(run / "headless-compatibility.json", {"commit": COMMIT, "changes": changes})
