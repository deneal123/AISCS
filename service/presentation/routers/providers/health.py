"""`GET /providers/health` — здоровье провайдеров глазами САЙДКАРА.

Отделено от приёма ключей (`keys.py`) намеренно: раньше обе ручки делили один файл
только потому, что у них общий префикс пути. Операции разные — одна читает состояние,
вторая принимает секреты.
"""

from __future__ import annotations

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from service.presentation.deps import internal_auth
from service.shared.provider_policy_context import describe as describe_policy

router = APIRouter(prefix="/providers")


@router.get("/health")
async def health(
    force: bool = False,
    only: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict:
    """Здоровье провайдеров глазами САЙДКАРА — он теперь единственный, кто им звонит.

    Панель админа исторически пробивала провайдеров из backend'а. После выноса движка это
    меряет не то: реальный трафик идёт отсюда, и circuit_breaker «по трафику» наполняется
    ТОЖЕ здесь (у сайдкара он in-memory, снаружи не виден вовсе).

    ``force=true`` — как кнопка «Проверить»: пробить всех по-настоящему, не доверяя
    breaker'у. Дороже, поэтому не по умолчанию.

    ``only=a,b`` — пробить ТОЧЕЧНО перечисленных. Для периодической самопроверки
    заблокированных: проба стоит настоящего вызова к провайдеру, и форсировать всех
    каждые несколько минут — это возврат к пуллингу, снятому намеренно.
    """
    internal_auth(authorization)
    # Пустая строка (`only=`) — это «никого», а не «всех»: иначе опечатка в вызове
    # молча превращает точечную проверку обратно в полный обход.
    names = None if only is None else {p.strip() for p in only.split(",") if p.strip()}
    try:
        from service.domain.client.health import compute_provider_health
    except Exception:  # noqa: BLE001 — движок не подан: та же причина, что у /run
        return JSONResponse(
            status_code=503,
            content={"error": "engine_unavailable", "detail": "unavailable"},
        )
    data = await compute_provider_health(force_probe=force, only=names)
    # Политику отдаём рядом: админке важно отличать «выключен админом» от «упал сам»,
    # а сайдкар знает её только из снимка — пусть будет видно, знает ли он её вообще.
    data["policy"] = describe_policy()
    return data
