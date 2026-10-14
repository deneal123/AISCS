"""Драйвер docker: контейнер на арендатора, через CLI демона.

CLI, а не python-SDK: docker-клиент уже есть в образе как зависимость развёртывания, а SDK
синхронный и тянул бы свой стек ради трёх команд. Разбор — только `--format '{{json .}}'`,
то есть JSON, а не парсинг человекочитаемого вывода.

🔴 УБИЙСТВО ХОСТОВОГО `docker exec` НЕ УБИВАЕТ ПРОЦЕСС ВНУТРИ КОНТЕЙНЕРА. Это главная
ловушка всего сервиса: по таймауту мы отпускаем клиента, а команда модели продолжает жечь
процессор арендаторов — и не видна снаружи вовсе. Поэтому команда запускается через
`setsid` с записью PGID в файл, а по таймауту группа добивается ВНУТРИ контейнера.

🔴 Изоляция ПРОВЕРЯЕТСЯ, а не заявляется: после создания `docker inspect` обязан
подтвердить сеть, привилегии, права на корень и потолки. Не подтвердил — контейнер
уничтожается, песочница не выдаётся.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shlex
import time
from collections.abc import Awaitable

from domain.policy import WorkspacePolicy

from drivers.base import (
    ContainerCreationCancelled,
    ContainerCreationFailed,
    ContainerCreationUncertain,
    ContainerCreationUncertainCancelled,
    ContainerRef,
    DriverError,
    ExecResult,
    IsolationUnverified,
    ManagedContainer,
)
from drivers.creation_cleanup import settle_creation
from drivers.isolation import inspection_complete
from drivers.isolation import isolation_complaints as _isolation_complaints

logger = logging.getLogger("workspace-sidecar.docker")

DRIVER_NAME = "docker"
# Сколько ждём саму команду docker (создание/инспекцию/удаление), а не работу внутри.
_CLI_TIMEOUT_SEC = 60.0
# Пауза между TERM и KILL группе процессов внутри контейнера.
_KILL_GRACE_SEC = 3.0
_PGID_FILE = "/tmp/.ws-exec.pgid"


async def _cancel_process_cleanup(
    proc: asyncio.subprocess.Process, group_cleanup: Awaitable[None] | None
) -> bool:
    try:
        try:
            if group_cleanup is not None:
                await asyncio.wait_for(group_cleanup, timeout=_KILL_GRACE_SEC + 12.0)
        finally:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            # Drain both pipes: wait() alone can deadlock when a command filled one.
            with contextlib.suppress(ProcessLookupError):
                await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except Exception:
        # A failed shielded task can itself be logged by asyncio after repeated cancellation.
        # Keep its result bounded instead of letting private exception text escape the task.
        return False
    return True


async def _settle_cancelled_process(
    proc: asyncio.subprocess.Process, group_cleanup: Awaitable[None] | None = None
) -> None:
    """Repeated request cancellation cannot interrupt bounded owned-process retirement."""
    cleanup = asyncio.create_task(_cancel_process_cleanup(proc, group_cleanup))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            if cleanup.cancelled():
                break  # Process shutdown cancelled the cleanup itself; do not spin.
        except Exception:
            break
    if not cleanup.cancelled() and not cleanup.result():
        logger.error(
            "workspace process cleanup failed",
            extra={"component": "workspace_driver", "failure_code": "process_cleanup_failed"},
        )


async def _docker(*args: str, timeout_sec: float = _CLI_TIMEOUT_SEC) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.CancelledError:
        await _settle_cancelled_process(proc)
        raise
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise DriverError(f"docker {args[0]} не ответил за {timeout_sec:.0f} с") from None
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _create_argv(
    workspace_id: str, policy: WorkspacePolicy, labels: dict[str, str] | None = None
) -> list[str]:
    """Аргументы `docker create`. Каждый флаг здесь — ограничение, а не настройка."""
    argv = [
        "create",
        "--init",
        "--name",
        f"gpthub-ws-{workspace_id}",
        "--label",
        "gpthub.workspace=1",
        # 🔴 Сеть по умолчанию `none`: содержимое песочницы пишет модель, и выход в
        # локальную сеть означал бы доступ к Postgres, Redis, MinIO и всем сайдкарам,
        # которые внутри периметра не спрашивают аутентификации.
        "--network",
        str(policy.network),
        "--memory",
        str(int(policy.memory_bytes)),
        # ⚠️ Без своп-лимита потолок памяти обходится свопом: контейнер «в пределах»
        # памяти утаскивает хост в своп целиком.
        "--memory-swap",
        str(int(policy.memory_bytes)),
        "--pids-limit",
        str(int(policy.pids_limit)),
        "--cpus",
        str(float(policy.cpus)),
        "--user",
        str(policy.user),
        # 🔴 Запрет повышения привилегий: setuid-бинарь внутри иначе даёт root в контейнере.
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
    ]
    for key, value in sorted((labels or {}).items()):
        if key != "gpthub.workspace":
            argv += ["--label", f"{key}={value}"]
    if policy.read_only_root:
        argv += ["--read-only"]
    # Рабочий каталог — единственное записываемое место, и с потолком размера: без него
    # `dd if=/dev/zero` заполняет диск ХОСТА, а не песочницы.
    argv += [
        "--tmpfs",
        f"{policy.root}:rw,exec,size={int(policy.quota_bytes)},mode=1777",
        "--workdir",
        str(policy.root),
        # tmpfs под /tmp нужен и при read-only корне: без него не запускается почти ничто.
        "--tmpfs",
        f"/tmp:rw,exec,size={int(policy.quota_bytes)},mode=1777",
        str(policy.image),
        "sleep",
        "infinity",
    ]
    return argv


class DockerCliDriver:
    """Контейнер на песочницу. Состояние наружу не выносит: ссылка — идентификатор."""

    name = DRIVER_NAME

    async def create(
        self, workspace_id: str, policy: WorkspacePolicy, *, labels: dict[str, str] | None = None
    ) -> ContainerRef:
        try:
            code, out, err = await _docker(*_create_argv(workspace_id, policy, labels))
        except asyncio.CancelledError:
            raise ContainerCreationUncertainCancelled from None
        except Exception:
            raise ContainerCreationUncertain from None
        if code != 0:
            raise DriverError(f"не удалось создать песочницу: {err.strip() or out.strip()}")
        container_id = out.strip()
        if len(container_id) != 64 or any(char not in "0123456789abcdef" for char in container_id):
            # A successful but malformed reply is not a safe destruction target.
            raise ContainerCreationUncertain
        ref = ContainerRef(DRIVER_NAME, container_id)
        try:
            code, _, _ = await _docker("start", container_id)
            if code != 0:
                raise DriverError("container start failed")
        except (Exception, asyncio.CancelledError) as exc:
            debt, interrupted = await settle_creation(ref, self.destroy)
            if interrupted or isinstance(exc, asyncio.CancelledError):
                raise ContainerCreationCancelled(debt) from None
            raise ContainerCreationFailed(debt) from None
        return ref

    async def list_managed(self) -> list[ManagedContainer]:
        code, out, _ = await _docker(
            "ps", "-aq", "--no-trunc", "--filter", "label=gpthub.workspace=1"
        )
        if code != 0:
            raise DriverError("docker discovery failed")
        found: list[ManagedContainer] = []
        for container_id in (line.strip() for line in out.splitlines()):
            if not container_id:
                continue
            code, details, _ = await _docker("inspect", container_id)
            if code != 0:
                continue
            try:
                payload = json.loads(details)[0]
                labels = dict((payload.get("Config") or {}).get("Labels") or {})
            except (IndexError, TypeError, json.JSONDecodeError):
                labels = {}
            found.append(ManagedContainer(ContainerRef(DRIVER_NAME, container_id), labels))
        return found

    async def verify_isolation(self, ref: ContainerRef, policy: WorkspacePolicy) -> None:
        """Сверить ЗАЯВЛЕННОЕ с ФАКТИЧЕСКИМ. Расхождение — отказ, а не предупреждение."""
        code, out, _ = await _docker("inspect", "--format", "{{json .}}", ref.container_id)
        if code != 0:
            raise DriverError("isolation inspection unavailable")
        try:
            info = json.loads(out)
        except ValueError:
            raise DriverError("isolation inspection unavailable") from None
        if not inspection_complete(info):
            raise DriverError("isolation inspection unavailable")
        for complaint in _isolation_complaints(info, policy):
            raise IsolationUnverified(complaint)

    async def exec_with_input(
        self,
        ref: ContainerRef,
        command: str,
        *,
        payload: bytes,
        timeout_sec: float,
        max_output_chars: int,
    ) -> ExecResult:
        """Команда, которой содержимое приходит ЧЕРЕЗ STDIN, а не в аргументах.

        🔴 ЗАЧЕМ ОТДЕЛЬНЫЙ ПУТЬ. Запись файла клала его base64 прямо в argv, а у Linux
        потолок ОДНОГО аргумента — 128 КБ (`MAX_ARG_STRLEN`), то есть ~96 КБ исходных байт.
        Любой настоящий архив это переполнял, и `execve` падал с `OSError: Argument list too
        long` ЕЩЁ ДО контейнера. Наружу это выглядело как «песочница есть, а файлов в ней
        нет»: заявленный потолок стоял 1 МБ и до дела не доходил.

        ⚠️ БЕЗ `setsid`-обёртки, в отличие от `exec`. Та существует, чтобы добить ГРУППУ
        процессов чужого кода по таймауту; фоновый запуск через `&` при этом отвязывает
        stdin, и содержимое до команды просто не доехало бы. Запись файла — не чужой код и
        группы не плодит, поэтому здесь путь прямой.
        """
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            "-i",
            ref.container_id,
            "/bin/sh",
            "-c",
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(payload), timeout=timeout_sec)
        except asyncio.CancelledError:
            await _settle_cancelled_process(proc)
            raise
        except TimeoutError:
            timed_out = True
            out, err = b"", b""
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
        stdout, cut_out = _clip(out.decode("utf-8", "replace"), max_output_chars)
        stderr, cut_err = _clip(err.decode("utf-8", "replace"), max_output_chars)
        return ExecResult(
            exit_code=-1 if timed_out else (proc.returncode or 0),
            stdout=stdout,
            stderr=stderr,
            truncated=cut_out or cut_err,
            duration_sec=round(time.monotonic() - started, 3),
            timed_out=timed_out,
        )

    async def exec(
        self, ref: ContainerRef, command: str, *, timeout_sec: float, max_output_chars: int
    ) -> ExecResult:
        started = time.monotonic()
        # ⚠️ `setsid` + запись PGID: по таймауту добивать надо ГРУППУ внутри контейнера,
        # иначе процесс переживает и вызов, и клиента.
        wrapped = f"setsid /bin/sh -c {shlex.quote(command)} & echo $! > {_PGID_FILE}; wait $!"
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            ref.container_id,
            "/bin/sh",
            "-c",
            wrapped,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        except asyncio.CancelledError:
            await _settle_cancelled_process(proc, self._kill_process_group(ref))
            raise
        except TimeoutError:
            timed_out = True
            out, err = b"", b""
            await self._kill_process_group(ref)
            # 🔴 Добивание группы ВНУТРИ контейнера завершает и хостовой `docker exec` — сам,
            # раньше нас. `proc.kill()` тогда бросает ProcessLookupError, и таймаут
            # превращался в 500 БЕЗ результата: клиент не получал ни вывода, ни признака
            # `timed_out`, то есть худший исход из возможных. Нашёл живой прогон — тесты
            # увидеть этого не могли, они подменяют драйвер целиком.
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
        stdout, cut_out = _clip(out.decode("utf-8", "replace"), max_output_chars)
        stderr, cut_err = _clip(err.decode("utf-8", "replace"), max_output_chars)
        return ExecResult(
            exit_code=-1 if timed_out else (proc.returncode or 0),
            stdout=stdout,
            stderr=stderr,
            truncated=cut_out or cut_err,
            duration_sec=round(time.monotonic() - started, 3),
            timed_out=timed_out,
        )

    async def _kill_process_group(self, ref: ContainerRef) -> None:
        """Добить группу процессов ВНУТРИ контейнера: TERM, пауза, KILL."""
        script = (
            f'pgid=$(cat {_PGID_FILE} 2>/dev/null); [ -n "$pgid" ] || exit 0; '
            f'kill -TERM -"$pgid" 2>/dev/null; sleep {_KILL_GRACE_SEC:.0f}; '
            f'kill -KILL -"$pgid" 2>/dev/null; exit 0'
        )
        try:
            await _docker(
                "exec",
                ref.container_id,
                "/bin/sh",
                "-c",
                script,
                timeout_sec=_KILL_GRACE_SEC + 10.0,
            )
        except DriverError:
            # Не добили — говорим ГРОМКО: это утечка процессора, которую иначе не увидеть.
            logger.error(
                "workspace process cleanup failed",
                extra={"component": "workspace_driver", "failure_code": "process_cleanup_failed"},
            )

    async def destroy(self, ref: ContainerRef) -> None:
        code, _, err = await _docker("rm", "-f", ref.container_id)
        if code != 0:
            raise DriverError("docker destroy failed")


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "…[обрезано]", True
