"""Trusted Git setup from verified pack bytes, never repository scripts or network."""

import ctypes
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time

from infrastructure.ide_bundle_runtime import _idle, _read_exact, _report, _watch

_lock = threading.RLock()
_child = None
_stage = None
_published = []
_root = None
_finished = False


def seed_digest(path):
    """Bounded no-follow comparison of Git-init bytes, modes and empty directories.

    Origin is supplied privately by the backend. Equality here proves only that
    replacing this seed loses no files, commits, refs, config or hooks.
    """
    digest, budget = hashlib.sha256(), [0, 0]

    def walk(parent, relative, depth):
        if depth > 8:
            raise ValueError("ide_git_not_empty")
        for name in sorted(os.listdir(parent)):
            budget[0] += 1
            if budget[0] > 64:
                raise ValueError("ide_git_not_empty")
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                info = os.fstat(fd)
                child = relative + "/" + name
                if info.st_uid != os.geteuid():
                    raise ValueError("ide_git_not_empty")
                digest.update(json.dumps([child, stat.S_IMODE(info.st_mode)]).encode())
                if stat.S_ISDIR(info.st_mode):
                    digest.update(b"directory")
                    walk(fd, child, depth + 1)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    content = os.read(fd, 16385)
                    budget[1] += len(content)
                    if len(content) != info.st_size or len(content) > 16384 or budget[1] > 65536:
                        raise ValueError("ide_git_not_empty")
                    digest.update(b"file" + hashlib.sha256(content).digest())
                else:
                    raise ValueError("ide_git_not_empty")
            finally:
                os.close(fd)

    root = None
    try:
        root = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(root)
        if info.st_uid != os.geteuid():
            raise ValueError("ide_git_not_empty")
        digest.update(json.dumps(["root", stat.S_IMODE(info.st_mode)]).encode())
        walk(root, "", 0)
    except OSError:
        raise ValueError("ide_git_not_empty") from None
    finally:
        if root is not None:
            os.close(root)
    return digest.digest()


def exchange_seed(root, stage):
    """Atomic Linux exchange, retaining the old seed inside owned staging."""
    library = ctypes.CDLL(None, use_errno=True)
    rename = library.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    staging = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if rename(parent, b".git", staging, b".git", 2):  # RENAME_EXCHANGE
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
    finally:
        os.close(staging)
        os.close(parent)


def branch_name(value):
    return (
        type(value) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", value)
        and not any(
            part in {"", ".", ".."} or part.startswith(".") or part.endswith((".lock", "."))
            for part in value.split("/")
        )
        and ".." not in value
    )


def cleanup():
    global _child, _stage
    with _lock:
        if _child is not None:
            if _child.poll() is None:
                os.killpg(_child.pid, signal.SIGKILL)
            _child.wait(timeout=2)
            _child = None
        if not _finished:
            for name, identity in reversed(_published):
                path = os.path.join(_root, name)
                current = os.lstat(path)
                if (current.st_dev, current.st_ino) != identity:
                    raise RuntimeError("publication_changed")
                os.rename(path, os.path.join(_stage, name))
        if _stage is not None:
            shutil.rmtree(_stage)  # Owned, unpredictable staging directory only.
            _stage = None


def git(directory, *args, source=None):
    global _child
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "0",
        "LC_ALL": "C",
    }
    with tempfile.TemporaryFile() as output:
        with _lock:
            _child = subprocess.Popen(
                [
                    "/usr/bin/git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.protectNTFS=true",
                    "-c",
                    "core.protectHFS=true",
                    "-c",
                    "protocol.allow=never",
                    "-C",
                    directory,
                    *args,
                ],
                env=env,
                stdin=source if source else subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                start_new_session=True,
            )
            child = _child
        try:
            code = child.wait(timeout=15)
            if code or output.tell() > 65536:
                raise ValueError("ide_git_failed")
        finally:
            with _lock:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)
                if _child is child:
                    _child = None


def status(root):
    target = os.path.join(root, ".git")
    if not os.path.lexists(target):
        return dict(initialized=False, branch=None)
    if not stat.S_ISDIR(os.lstat(target).st_mode):
        raise ValueError("ide_git_conflict")
    fd = os.open(os.path.join(target, "HEAD"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("ide_git_conflict")
        value = os.read(fd, 256).decode("ascii").strip()
    finally:
        os.close(fd)
    branch = value.removeprefix("ref: refs/heads/")
    return dict(initialized=True, branch=branch if branch_name(branch) else None)


def setup(request, pack):
    global _stage, _root, _finished
    _root = request["root"]
    operation, branch = request["operation"], request["branch"]
    replace_seed = request.get("replace_pristine_starter", False)
    if type(replace_seed) is not bool or (replace_seed and operation != "clone"):
        raise ValueError("ide_git_invalid")
    if operation == "status":
        return status(_root)
    if operation not in {"init", "clone"} or not branch_name(branch):
        raise ValueError("ide_git_invalid")
    existing_git = status(_root)["initialized"]
    replacing = existing_git and replace_seed
    if existing_git and not replacing:
        if operation == "init":
            return status(_root)
        raise ValueError("ide_git_conflict")
    if operation == "clone" and set(os.listdir(_root)) != ({".git"} if replacing else set()):
        raise ValueError("ide_git_not_empty")
    if operation == "clone" and (
        not re.fullmatch(r"[a-f0-9]{40}", request["commit"])
        or not re.fullmatch(
            r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", request["origin"]
        )
        or not pack.startswith(b"PACK")
    ):
        raise ValueError("ide_git_invalid")
    _stage = tempfile.mkdtemp(prefix=".gpthub-git-", dir=_root)
    git(_stage, "init", "--template=", "--initial-branch=" + ("main" if replacing else branch))
    expected_seed = seed_digest(os.path.join(_stage, ".git")) if replacing else None
    if replacing:
        if seed_digest(os.path.join(_root, ".git")) != expected_seed:
            raise ValueError("ide_git_not_empty")
        git(_stage, "symbolic-ref", "HEAD", "refs/heads/" + branch)
    if operation == "clone":
        with tempfile.TemporaryFile() as source:
            source.write(pack)
            source.seek(0)
            git(_stage, "index-pack", "--stdin", "--strict", source=source)
        git(_stage, "update-ref", "refs/heads/" + branch, request["commit"])
        git(_stage, "update-ref", "refs/remotes/origin/" + branch, request["commit"])
        git(_stage, "config", "remote.origin.url", request["origin"])
        git(_stage, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
        git(_stage, "config", "branch." + branch + ".remote", "origin")
        git(_stage, "config", "branch." + branch + ".merge", "refs/heads/" + branch)
        git(_stage, "read-tree", "--reset", "-u", "HEAD")
    with _lock:
        if time.time() >= request["deadline"]:
            raise ValueError("ide_runtime_expired")
        names = os.listdir(_stage)
        if operation == "init":
            names = [".git"]
        elif set(os.listdir(_root)) != (
            {os.path.basename(_stage), ".git"} if replacing else {os.path.basename(_stage)}
        ):
            raise ValueError("ide_git_not_empty")
        for name in names:
            if replacing and name == ".git":
                continue
            if os.path.lexists(os.path.join(_root, name)):
                raise ValueError("ide_git_conflict")
            item = os.lstat(os.path.join(_stage, name))
            os.rename(os.path.join(_stage, name), os.path.join(_root, name))
            _published.append((name, (item.st_dev, item.st_ino)))
        if replacing:
            # Recheck after staging/checkout and before exchanging any Git state.
            if seed_digest(os.path.join(_root, ".git")) != expected_seed:
                raise ValueError("ide_git_not_empty")
            exchange_seed(_root, _stage)
        _finished = True
    cleanup()
    return dict(initialized=True, branch=branch)


def main():
    try:
        header = bytearray()
        while len(header) <= 8192:
            char = _read_exact(1)
            if char == b"\n":
                break
            header.extend(char)
        else:
            raise ValueError("ide_git_invalid")
        request = json.loads(header)
        size = request["input_size"]
        if type(size) is not int or not 0 <= size <= 20 * 1024 * 1024:
            raise ValueError("ide_git_limit")
        pack = _read_exact(size)
        if hashlib.sha256(pack).hexdigest() != request["input_sha256"] or _read_exact(1) != b"\x01":
            raise ValueError("ide_git_invalid")
        threading.Thread(target=_watch, args=(cleanup,), daemon=True).start()
        _idle()
        if time.time() >= request["deadline"]:
            raise ValueError("ide_runtime_expired")
        result = setup(request, pack)
    except BaseException as error:
        try:
            cleanup()
        except BaseException:
            os._exit(75)
        code = str(error) if type(error) is ValueError else "ide_git_unconfirmed"
        if code not in {
            "ide_git_conflict",
            "ide_git_not_empty",
            "ide_git_invalid",
            "ide_git_limit",
            "ide_runtime_expired",
            "ide_git_failed",
        }:
            code = "ide_git_unconfirmed"
        result = {"error": code}
    os.write(1, json.dumps(result, separators=(",", ":")).encode())
    _report({"status": "ok", "operation": "git"})
    os._exit(0)
