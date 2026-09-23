"""Какие MCP-серверы доступны этому прогону.

🔴 URL НИКОГДА НЕ ПРИХОДИТ ИЗ ТЕЛА ЗАПРОСА. Это прямой SSRF во внутреннюю сеть, где
Postgres, Redis, MinIO, Qdrant и все сайдкары доступны без аутентификации по топологии, —
причём из поля, которым полностью управляет пользователь. Серверы объявляет АДМИН, а тенанту
приезжает лишь список разрешённых ИДЕНТИФИКАТОРОВ.

Итоговый набор — пересечение трёх множеств: объявлено админом ∩ разрешено тенанту ∩ включено.
Пересечение, а не объединение: любое из трёх «нет» должно означать «нет».
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Транспорты только сетевые. `stdio` не поддерживаем СОЗНАТЕЛЬНО: он означал бы запуск
# подпроцесса внутри контейнера агентов — то есть исполнение чужого кода там, где его быть
# не должно ни при каких настройках.
SUPPORTED_TRANSPORTS = ("streamable_http", "sse")


@dataclass(frozen=True, slots=True)
class ServerRef:
    """Один объявленный сервер. Секреты наружу не отдаются."""

    id: str
    url: str
    transport: str = "streamable_http"
    auth_header: str = ""
    auth_token: str = ""
    allowed_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.transport not in SUPPORTED_TRANSPORTS:
            raise ValueError(f"{self.id}: транспорт {self.transport!r} не поддерживается")
        if not self.url.startswith(("http://", "https://")):
            raise ValueError(f"{self.id}: адрес должен быть http(s)")


def resolve_servers(declared: list | None, requested_ids: list[str] | None) -> list[ServerRef]:
    """Объявлено админом ∩ разрешено тенанту ∩ включено.

    ⚠️ `requested_ids is None` означает «тенанту не разрешено ничего», а НЕ «разрешено всё».
    Умолчание на стороне безопасности: забытое поле в контракте не должно открывать доступ.
    """
    if not declared or not requested_ids:
        return []
    allowed = {str(x).strip() for x in requested_ids if str(x).strip()}
    out: list[ServerRef] = []
    for item in declared:
        if not isinstance(item, dict):
            continue
        server_id = str(item.get("id") or "").strip()
        if not server_id or server_id not in allowed:
            continue
        if not item.get("enabled", True):
            continue
        try:
            out.append(
                ServerRef(
                    id=server_id,
                    url=str(item.get("url") or "").strip(),
                    transport=str(item.get("transport") or "streamable_http").strip(),
                    auth_header=str(item.get("auth_header") or "").strip(),
                    auth_token=str(item.get("auth_token") or "").strip(),
                    allowed_tools=tuple(str(t) for t in (item.get("allowed_tools") or ())),
                )
            )
        except ValueError:
            # Кривое объявление — пропускаем ГРОМКО: молча выпавший сервер выглядит как
            # «инструментов у него нет», и разбираться пришлось бы по чужим логам.
            logger.error("MCP server configuration rejected code=invalid")
    return out
