"""Жизненный цикл одного llama-server; без HTTP, конфигурации и agent loop."""

import signal
import subprocess
import threading


def run(server, command, child):
    stopped = threading.Event()
    process = None
    try:
        process = subprocess.Popen(
            command,
            env=child,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def stop(signum, frame):
            stopped.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

        def watch():
            process.wait()
            if not stopped.is_set():
                server.shutdown()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        threading.Thread(target=watch, daemon=True).start()
        server.serve_forever(poll_interval=0.1)
        return 0 if stopped.is_set() else 1
    except OSError:
        print("local_llm_runtime_unavailable", flush=True)
        return 1
    finally:
        server.server_close()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
