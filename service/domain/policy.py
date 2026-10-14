"""Политика песочницы: что заперто при создании и что правится на живой.

🔴 РАЗДЕЛЕНИЕ — САМА СУТЬ МОДУЛЯ, а не способ разложить поля. Статическая половина
описывает, ДО ЧЕГО процесс может дотянуться (образ, сеть, права на корень, потолки памяти и
процессов); горячая — сколько ему дают на ОДИН вызов. Первое, изменённое на работающей
песочнице, есть повышение привилегий по расписанию: контейнер создавался под одни права, а
работает под другими, и заметить это по логам нечем.

Приём подсмотрен у NVIDIA OpenShell (там filesystem+process заперты при создании, а
network+inference горячие) — сам рантайм не берём: он однопользовательский по их же
описанию, а это ровно та граница, ради которой сайдкар и заводится.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from math import isfinite
from pathlib import PurePosixPath
from typing import Any

from domain.contracts import (
    DEFAULT_EXEC_TIMEOUT_SEC,
    DEFAULT_IMAGE,
    DEFAULT_MAX_OUTPUT_CHARS,
    DYNAMIC_POLICY_FIELDS,
    HARD_EXEC_TIMEOUT_SEC,
    STATIC_POLICY_FIELDS,
)


class StaticPolicyLocked(Exception):
    """Попытка изменить запертое поле на живой песочнице."""


@dataclass(frozen=True, slots=True)
class WorkspacePolicy:
    """Одна политика: обе половины рядом, но правится только вторая.

    ⚠️ Дефолты — САМЫЕ УЗКИЕ из осмысленных: без сети, корень только для чтения, работа
    не от root. Расширять их обязан вызывающий явным полем; забытое поле должно означать
    «нельзя», а не «можно».
    """

    # --- статическая половина (заперта при создании) ---
    # ⚠️ Образ — из окружения, а не литералом: истории версий нужен `git`, и какой
    # рантайм подан, решает развёртывание (см. `contracts.DEFAULT_IMAGE`).
    image: str = DEFAULT_IMAGE
    network: str = "none"
    read_only_root: bool = True
    memory_bytes: int = 512 * 1024 * 1024
    pids_limit: int = 256
    cpus: float = 1.0
    user: str = "65534:65534"
    quota_bytes: int = 256 * 1024 * 1024
    root: str = "/workspace"
    # --- горячая половина ---
    exec_timeout_sec: float = DEFAULT_EXEC_TIMEOUT_SEC
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS

    def __post_init__(self) -> None:
        # ⚠️ Проверка ЗДЕСЬ, а не в конструкторе запроса: политика собирается и из тела
        # запроса, и из дефолтов сервиса, и из горячей правки — проверять надо объект, а
        # не каждую из трёх дорог к нему.
        for name in ("memory_bytes", "pids_limit", "quota_bytes", "max_output_chars"):
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= 2**63 - 1:
                raise ValueError(f"invalid policy field: {name}")
        for name in ("cpus", "exec_timeout_sec"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not 0 < value <= 2**63 - 1 or not isfinite(value):
                raise ValueError(f"invalid policy field: {name}")
        if not 1 <= self.cpus * 1_000_000_000 <= 2**63 - 1:
            raise ValueError("invalid policy field: cpus")
        if type(self.read_only_root) is not bool:
            raise ValueError("invalid policy field: read_only_root")
        for name in ("image", "network", "user"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or len(value.encode("utf-8")) > 4096
                or value.startswith("-")
                or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError(f"invalid policy field: {name}")
        if (
            not isinstance(self.root, str)
            or not self.root.startswith("/")
            or self.root == "/"
            or self.root.startswith("//")
            or len(self.root.encode("utf-8")) > 4096
            or self.root != str(PurePosixPath(self.root))
            or ".." in PurePosixPath(self.root).parts
            or any(char in ":,\\" or ord(char) < 32 or ord(char) == 127 for char in self.root)
        ):
            raise ValueError("invalid policy field: root")
        if self.exec_timeout_sec > HARD_EXEC_TIMEOUT_SEC:
            raise ValueError(f"exec_timeout_sec вне (0, {HARD_EXEC_TIMEOUT_SEC}]")

    def with_update(self, update: dict[str, Any]) -> WorkspacePolicy:
        """Горячая правка. Запертое поле — ОТКАЗ, а не частичное применение.

        🔴 Отказ на ПЕРВОМ же запертом поле и до применения любых изменений: применить
        горячую часть и отвергнуть статическую значило бы оставить песочницу в состоянии,
        которого не просил никто.
        """
        touched = {k for k, v in (update or {}).items() if v is not None}
        locked = sorted(touched & STATIC_POLICY_FIELDS)
        if locked:
            raise StaticPolicyLocked(
                f"поля заперты при создании и не меняются на живой песочнице: {', '.join(locked)}"
            )
        unknown = sorted(touched - DYNAMIC_POLICY_FIELDS)
        if unknown:
            raise ValueError(f"неизвестные поля политики: {', '.join(unknown)}")
        return replace(self, **{k: update[k] for k in touched})

    def as_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def policy_from_request(payload: dict[str, Any] | None) -> WorkspacePolicy:
    """Политика из тела запроса. Неизвестное поле — ошибка, а не тихий пропуск.

    ⚠️ Молча проигнорированное поле политики — худший из возможных исходов: вызывающий
    считает, что ограничение применено, а его нет.
    """
    data = dict(payload or {})
    known = STATIC_POLICY_FIELDS | DYNAMIC_POLICY_FIELDS
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"неизвестные поля политики: {', '.join(unknown)}")
    return WorkspacePolicy(**{k: v for k, v in data.items() if v is not None})
