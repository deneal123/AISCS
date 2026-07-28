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
from typing import Any

from contracts import (
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
        if self.exec_timeout_sec <= 0 or self.exec_timeout_sec > HARD_EXEC_TIMEOUT_SEC:
            raise ValueError(f"exec_timeout_sec вне (0, {HARD_EXEC_TIMEOUT_SEC}]")
        if self.max_output_chars <= 0:
            raise ValueError("max_output_chars должен быть положительным")
        if not str(self.root).startswith("/"):
            raise ValueError("root должен быть абсолютным путём")

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
