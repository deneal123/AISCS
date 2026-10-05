"""Attach commit-pinned sparse checkouts as superproject submodules."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys

sys.dont_write_bytecode = True
from inventory import REGISTRY, ROOT, WORK, load, save

ENV = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1", GIT_TERMINAL_PROMPT="0")


def stop_tree(process):
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.communicate(timeout=10)


def git(args, cwd, log, timeout=600, input_text=None):
    process = subprocess.Popen(
        ["git", "-c", "pack.threads=4", *args],
        cwd=cwd,
        env=ENV,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_tree(process)
        with log.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                "$ git " + " ".join(args) + "\nTIMEOUT: owned process tree stopped\n"
            )
        raise
    with log.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write("$ git " + " ".join(args) + "\n" + stdout + stderr + "\n")
    if process.returncode:
        raise RuntimeError(stderr.strip()[:700])
    return stdout.strip()


def select_commit(row, resolve_head):
    if (
        row.get("commit")
        and row.get("recorded_commit")
        and row["commit"] != row["recorded_commit"]
    ):
        raise ValueError("Registered baseline pin differs from requested checkout")
    return row.get("commit") or row.get("recorded_commit") or resolve_head()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", action="append", default=[])
    args = parser.parse_args()
    data = load(REGISTRY)
    for row in data["candidates"]:
        if args.id and row["id"] not in args.id:
            continue
        path = (ROOT / row["path"]).resolve()
        if not path.is_relative_to((ROOT / "simulation/sidecars").resolve()):
            raise ValueError("Repository path outside sidecars")
        task = WORK / row["id"] / "acquire"
        task.mkdir(parents=True, exist_ok=True)
        log = task / "git.log"
        try:
            if not (path / ".git").exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                git(
                    [
                        "clone",
                        "--filter=blob:none",
                        "--no-checkout",
                        row["url"],
                        str(path),
                    ],
                    ROOT,
                    log,
                )
            commit = select_commit(
                row,
                lambda path=path, log=log: git(["rev-parse", "origin/HEAD"], path, log),
            )
            if not row.get("commit"):
                row["commit"] = commit
            # A clone made with --no-checkout has an empty index and reports
            # every tracked path as deleted. Only accept that initialization
            # state when the worktree also contains nothing except .git.
            uninitialized = not git(["ls-files"], path, log) and all(
                p.name == ".git" for p in path.iterdir()
            )
            if not uninitialized and git(["status", "--porcelain"], path, log):
                raise RuntimeError("Existing upstream worktree is dirty; preserving it")
            # Keep large datasets out of Git checkout. Runtime fetches exactly declared assets separately.
            # set initializes sparse checkout itself. init first would fetch
            # the default root selection, including large upstream datasets.
            patterns = task / "sparse-patterns.txt"
            source_patterns = [
                "*.py",
                "*.R",
                "*.r",
                "*.jl",
                "*.m",
                "*.ipynb",
                "*.js",
                "*.mjs",
                "*.cjs",
                "*.ts",
                "*.tsx",
                "*.jsx",
                "*.c",
                "*.cpp",
                "*.h",
                "*.hpp",
                "*.rs",
                "*.wgsl",
                "*.sh",
                "*.bat",
                "*.ps1",
                "*.md",
                "*.rst",
                "*.toml",
                "*.yml",
                "*.yaml",
                "*.txt",
                "*.cfg",
                "*.ini",
                "*.xml",
                "*.css",
                "*.scss",
                "*.bib",
                "*.jsonl",
                "LICENSE*",
                "license*",
                "COPYING*",
                "copying*",
                "Makefile",
                "Dockerfile*",
                ".git*",
                "package.json",
                "package-lock.json",
                "tsconfig*.json",
                "index.html",
                "!*.egg-info/",
                "!node_modules/",
                "!/data/",
                "!/datasets/",
                "!/results/",
                "!/trained_models/",
                "!/pretrained_models/",
            ]
            if row["repository"] == "TuragaLab/flyvis":
                source_patterns.append("/flyvis/connectome/*.json")
            if row["repository"] == "artem-x-meta/fly-arena":
                source_patterns.append("/fly_circuit_lab/parameters/*.json")
            pattern_text = "\n".join(source_patterns)
            patterns.write_text(pattern_text + "\n", encoding="utf-8", newline="\n")
            git(
                ["sparse-checkout", "set", "--no-cone", "--stdin"],
                path,
                log,
                input_text=patterns.read_text("utf-8"),
            )
            git(["checkout", "--detach", commit], path, log)
            name = "simulation/" + row["id"]
            modules = (ROOT / ".gitmodules").read_text("utf-8")
            if f'[submodule "{name}"]' not in modules:
                git(
                    ["submodule", "add", "--name", name, "--", row["url"], row["path"]],
                    ROOT,
                    log,
                )
            actual = git(["rev-parse", "HEAD"], path, log)
            if actual != commit:
                raise RuntimeError("Checkout commit mismatch")
            row.update(
                status="attached",
                commit=actual,
                sparse_checkout=True,
                checkout_clean=not bool(git(["status", "--porcelain"], path, log)),
            )
            print(row["id"], row["repository"], "attached", actual[:12], flush=True)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            row.update(status="acquisition_blocked", acquisition_error=str(exc)[:1000])
            print(row["id"], row["repository"], "blocked", str(exc)[:110], flush=True)
        save(REGISTRY, data)
    print("Acquisition complete", flush=True)


if __name__ == "__main__":
    main()
