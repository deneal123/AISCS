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

from drivers.base import ContainerRef, DriverError, ExecResult, IsolationUnverified
from policy import WorkspacePolicy

logger = logging.getLogger("workspace-sidecar.docker")

DRIVER_NAME = "docker"
# Сколько ждём саму команду docker (создание/инспекцию/удаление), а не работу внутри.
_CLI_TIMEOUT_SEC = 60.0
# Пауза между TERM и KILL группе процессов внутри контейнера.
_KILL_GRACE_SEC = 3.0
_PGID_FILE = "/tmp/.ws-exec.pgid"


async def _docker(*args: str, timeout_sec: float = _CLI_TIMEOUT_SEC) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise DriverError(f"docker {args[0]} не ответил за {timeout_sec:.0f} с") from None
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _create_argv(workspace_id: str, policy: WorkspacePolicy) -> list[str]:
    """Аргументы `docker create`. Каждый флаг здесь — ограничение, а не настройка."""
    argv = [
        "create",
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

    async def create(self, workspace_id: str, policy: WorkspacePolicy) -> ContainerRef:
        code, out, err = await _docker(*_create_argv(workspace_id, policy))
        if code != 0:
            raise DriverError(f"не удалось создать песочницу: {err.strip() or out.strip()}")
        container_id = out.strip()
        code, _, err = await _docker("start", container_id)
        if code != 0:
            await self.destroy(ContainerRef(DRIVER_NAME, container_id))
            raise DriverError(f"не удалось запустить песочницу: {err.strip()}")
        return ContainerRef(DRIVER_NAME, container_id)

    async def verify_isolation(self, ref: ContainerRef, policy: WorkspacePolicy) -> None:
        """Сверить ЗАЯВЛЕННОЕ с ФАКТИЧЕСКИМ. Расхождение — отказ, а не предупреждение."""
        code, out, err = await _docker("inspect", "--format", "{{json .}}", ref.container_id)
        if code != 0:
            raise IsolationUnverified(f"инспекция не удалась: {err.strip()}")
        try:
            info = json.loads(out)
        except ValueError as exc:
            raise IsolationUnverified("инспекция вернула не JSON") from exc
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
            logger.error("не удалось добить группу процессов в песочнице %s", ref.container_id)

    async def destroy(self, ref: ContainerRef) -> None:
        code, _, err = await _docker("rm", "-f", ref.container_id)
        if code != 0:
            logger.warning("не удалось удалить контейнер %s: %s", ref.container_id, err.strip())


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "…[обрезано]", True


def _isolation_complaints(info: dict, policy: WorkspacePolicy) -> list[str]:
    """Чем факт разошёлся с заявленным. Пусто — изоляция подтверждена.

    ⚠️ Отдельной функцией, потому что это ЕДИНСТВЕННОЕ место, где написано, что мы вообще
    считаем песочницей. Спрятанное внутри метода, оно проверялось бы только через docker.
    """
    host = (info or {}).get("HostConfig") or {}
    complaints: list[str] = []
    if str(host.get("NetworkMode") or "") != str(policy.network):
        complaints.append(
            f"сеть контейнера {host.get('NetworkMode')!r}, а политика требует {policy.network!r}"
        )
    if host.get("Privileged"):
        complaints.append("контейнер привилегированный")
    if host.get("CapAdd"):
        complaints.append(f"добавлены возможности ядра: {host.get('CapAdd')}")
    if policy.read_only_root and not host.get("ReadonlyRootfs"):
        complaints.append("корень не только для чтения")
    if int(host.get("Memory") or 0) <= 0:
        complaints.append("потолок памяти не выставлен")
    if int(host.get("PidsLimit") or 0) <= 0:
        complaints.append("потолок числа процессов не выставлен")
    return complaints
