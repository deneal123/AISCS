"""Ограниченная приватная диагностика процесса; наружу выходят только закрытые коды."""

MAX_DIAGNOSTIC_BYTES = 8192
EXIT_REASONS = {
    -4: "signal_illegal_instruction",
    -6: "signal_aborted",
    -9: "signal_killed",
    -11: "signal_segmentation_fault",
}
STDERR_REASONS = (
    ((b"unknown argument", b"unrecognized option", b"invalid argument"), "invalid_arguments"),
    ((b"cannot allocate memory", b"out of memory", b"bad_alloc"), "memory_allocation_failed"),
    (
        (b"error while loading shared libraries", b"cannot open shared object file"),
        "shared_library_unavailable",
    ),
    ((b"permission denied",), "runtime_permission_denied"),
    ((b"address already in use",), "runtime_bind_conflict"),
    ((b"failed to load model", b"error loading model"), "model_load_failed"),
)


class RuntimeDiagnostics:
    def __init__(self):
        self._tail = b""

    def consume(self, stream):
        # Читаем весь pipe, чтобы ребёнок не завис на заполненном stderr; храним
        # только хвост. Ни текст ошибок, ни окружение, ни команда не публикуются.
        try:
            with stream:
                while chunk := stream.read(4096):
                    self._tail = (self._tail + chunk)[-MAX_DIAGNOSTIC_BYTES:]
        except OSError:
            pass

    def reason(self, exit_code):
        if exit_code in EXIT_REASONS:
            return EXIT_REASONS[exit_code]
        if exit_code == 0:
            return "unexpected_clean_exit"
        tail = self._tail.lower()
        for patterns, reason in STDERR_REASONS:
            if any(pattern in tail for pattern in patterns):
                return reason
        return "runtime_exit"
