"""Immutable, unprivileged subreaper. Only this parent writes control frames.

User output is captured, never interpreted as a lifecycle message. Exit zero
belongs to the supervisor's confirmed cleanup, not the user's command result.
"""

import ctypes
import json
import os
import selectors
import signal
import subprocess
import sys
import time

stopping = False


def interrupted(*_):
    global stopping
    stopping = True


def start_time(pid):
    with open(f"/proc/{pid}/stat", encoding="ascii") as source:
        return source.read().rsplit(")", 1)[1].split()[19]


def children(pid):
    try:
        with open(f"/proc/{pid}/task/{pid}/children", encoding="ascii") as source:
            return [int(value) for value in source.read().split()]
    except FileNotFoundError:
        return []


def descendants(pid):
    pending, found = children(pid), {}
    while pending:
        child = pending.pop()
        if child in found:
            continue
        try:
            found[child] = start_time(child)
            pending.extend(children(child))
        except FileNotFoundError:
            pass
        if len(found) > 1024:
            raise RuntimeError("process_limit")
    return found


def signal_descendants(sig):
    for pid, identity in descendants(os.getpid()).items():
        try:
            descriptor = os.pidfd_open(pid)
            try:
                if start_time(pid) == identity:
                    signal.pidfd_send_signal(descriptor, sig)
            finally:
                os.close(descriptor)
        except ProcessLookupError:
            pass
        except FileNotFoundError:
            pass


def cleanup(process):
    signal_descendants(signal.SIGTERM)
    until = time.monotonic() + 3
    while process.poll() is None and time.monotonic() < until:
        time.sleep(0.02)
    signal_descendants(signal.SIGKILL)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return False
    until = time.monotonic() + 3
    empty = 0
    while time.monotonic() < until:
        signal_descendants(signal.SIGKILL)
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG)[0] == 0:
                    break
            except ChildProcessError:
                break
        if not children(os.getpid()):
            empty += 1
            if empty == 2:
                return True
        else:
            empty = 0
        time.sleep(0.02)
    return False


def emit(body):
    try:
        sys.stdout.write(json.dumps(body, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    except (BrokenPipeError, OSError):
        # Output loss does not interrupt cleanup or manufacture verification.
        pass


def control(waiter):
    """A partial GO frame must not disable Stop or the handshake deadline."""
    os.set_blocking(sys.stdin.fileno(), False)
    raw = bytearray()
    until = time.monotonic() + 60
    while not stopping and time.monotonic() < until:
        if not waiter.select(0.05):
            continue
        value = os.read(sys.stdin.fileno(), 65537 - len(raw))
        if not value:
            return None
        raw.extend(value)
        if len(raw) > 65536:
            raise ValueError("control_limit")
        if b"\n" in raw:
            line, rest = raw.split(b"\n", 1)
            if rest:
                raise ValueError("control_invalid")
            return json.loads(line)
    return None


def run(config):
    timeout, limit = config["timeout_sec"], config["output_limit"]
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
        raise ValueError("timeout_invalid")
    if type(limit) is not int or not 1 <= limit <= 20000:
        raise ValueError("limit_invalid")
    argv = config["argv"]
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 128
        or any(not isinstance(part, str) or len(part) > 16384 or "\0" in part for part in argv)
    ):
        raise ValueError("argv_invalid")
    began = time.monotonic()
    report_read, report_write = None, None
    profile = config.get("verification_profile")
    if profile is not None:
        if profile not in {"unittest", "pytest"}:
            raise ValueError("profile_invalid")
        report_read, report_write = os.pipe()
        argv = [
            "python3",
            "-I",
            "/opt/gpthub-harness/verify.py",
            profile,
            config["verification_target"],
            str(report_write),
        ]
    process = subprocess.Popen(
        argv,
        cwd="/workspace",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
        pass_fds=() if report_write is None else (report_write,),
    )
    if report_write is not None:
        os.close(report_write)
        os.set_blocking(report_read, False)
    capture = selectors.DefaultSelector()
    for name in ("stdout", "stderr"):
        pipe = getattr(process, name)
        os.set_blocking(pipe.fileno(), False)
        capture.register(pipe, selectors.EVENT_READ, name)
    output = {"stdout": bytearray(), "stderr": bytearray()}
    cut = False
    timed_out = False
    try:
        while process.poll() is None:
            timed_out = time.monotonic() - began >= timeout
            if timed_out or stopping:
                break
            for key, _ in capture.select(0.05):
                value = os.read(key.fd, 65536)
                if not value:
                    capture.unregister(key.fileobj)
                    continue
                target = output[key.data]
                available = max(0, limit - len(target))
                target.extend(value[:available])
                cut |= len(value) > available
        code = process.poll()
        confirmed = cleanup(process)
        # Drain bounded remaining bytes after all writers have been retired.
        for key in list(capture.get_map().values()):
            while True:
                try:
                    value = os.read(key.fd, 65536)
                except BlockingIOError:
                    break
                if not value:
                    break
                target = output[key.data]
                available = max(0, limit - len(target))
                target.extend(value[:available])
                cut |= len(value) > available
        verification = None
        if report_read is not None:
            try:
                verification = json.loads(os.read(report_read, 4097))
            except (ValueError, OSError):
                pass
        emit(
            {
                "type": "done",
                "version": 1,
                "cleanup_confirmed": confirmed,
                "cancelled": stopping,
                "verification": verification,
                "result": {
                    "exit_code": process.returncode if code is None else code,
                    "stdout": output["stdout"].decode("utf-8", "replace"),
                    "stderr": output["stderr"].decode("utf-8", "replace"),
                    "truncated": cut,
                    "duration_sec": time.monotonic() - began,
                    "timed_out": timed_out,
                },
            }
        )
        return 0 if confirmed else 74
    finally:
        if process.poll() is None:
            cleanup(process)
        if report_read is not None:
            os.close(report_read)
        capture.close()
        process.stdout.close()
        process.stderr.close()


def main():
    operation = sys.argv[1]
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0 or libc.prctl(4, 0, 0, 0, 0) != 0:
        return 75
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    emit(
        {
            "type": "ready",
            "version": 1,
            "operation_id": operation,
            "pid": os.getpid(),
            "start_time": start_time(os.getpid()),
        }
    )
    waiter = selectors.DefaultSelector()
    waiter.register(sys.stdin, selectors.EVENT_READ)
    try:
        config = control(waiter)
        if config is None or stopping:
            return 0
        if (
            not isinstance(config, dict)
            or type(config.get("version")) is not int
            or config.get("version") != 1
            or config.get("operation_id") != operation
            or config.get("action") != "run"
        ):
            return 76
        return run(config)
    finally:
        waiter.close()


if __name__ == "__main__":
    try:
        status = main()
    except BaseException:
        status = 77  # Unexpected interruption is never a cleanup receipt.
    os._exit(status)
