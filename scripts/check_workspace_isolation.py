"""Сайдкар песочницы смотрит НАРУЖУ, но не внутрь.

🔴 ДВА ТРЕБОВАНИЯ, И ОНИ ПРОТИВОПОЛОЖНЫ ПО НАПРАВЛЕНИЮ.

**Наружу — обязательно.** Файлы пользователя лежат во ВНЕШНЕМ объектном хранилище, а
импорт идёт ССЫЛКАМИ: качает сам сайдкар. Стоя только в `internal` (сеть без интернета),
он не мог разрешить даже имя хранилища — импорт падал ВСЕГДА, и рабочий каталог был пуст
при «приложенном» файле. Найдено живым прогоном: «Unable to resolve host: s3.…».

**Внутрь — нельзя.** Это единственный сервис, которому отдан `docker.sock`. Тир хранилищ
(postgres, redis, qdrant, neo4j) и прочие сайдкары стоят в `internal` без аутентификации
по топологии: доступ туда у самого привилегированного контейнера — это не «шире
поверхность», это отсутствие границы.

⚠️ ЭТА ПРОВЕРКА — ВТОРАЯ ПОЛОВИНА. Первая живёт в коде: `net_guard` резолвит адрес перед
скачиванием и отвергает приватный/loopback/link-local. Сеть перенастраивают правкой в
compose, код — нет; поэтому и проверок две, и обе про одно.

⚠️ Песочницы арендаторов это НЕ ЗАТРАГИВАЕТ: их контейнеры создаются с `network: none`
(`policy.WorkspacePolicy.network`), и код пользователя остаётся без сети. Наружу ходит
только сайдкар и только за импортом — это тоже проверяется здесь.

Зависимостей нет — только stdlib.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = [ROOT / "docker" / "docker-compose.yaml", ROOT / "docker" / "docker-compose.dev.yaml"]
POLICY_CANDIDATES = (
    ROOT / "workspace" / "service" / "domain" / "policy.py",
    ROOT / "workspace" / "service" / "policy.py",
)


def _service_block(text: str, service: str) -> str | None:
    match = re.search(rf"\n  {service}:\n(.*?)(?=\n  [a-z0-9_-]+:\n|\Z)", text, re.S)
    return match.group(1) if match else None


def _networks(block: str) -> list[str]:
    section = re.search(r"^    networks:\n((?:\s+(?:#.*|- .+)\n)+)", block, re.M)
    if not section:
        return []
    return re.findall(r"^\s+- ([a-z0-9_-]+)\s*$", section.group(1), re.M)


def check_compose() -> list[str]:
    problems: list[str] = []
    for path in COMPOSE:
        if not path.exists():
            problems.append(f"{path.name}: файла нет")
            continue
        block = _service_block(path.read_text(encoding="utf-8"), "workspace")
        if block is None:
            problems.append(f"{path.name}: сервис `workspace` не найден")
            continue
        nets = _networks(block)
        if "internal" in nets:
            problems.append(
                f"{path.name}: `workspace` вернули в сеть `internal` — сервису с docker.sock "
                "снова доступны postgres, redis, qdrant и соседние сайдкары"
            )
        if "default" not in nets:
            problems.append(
                f"{path.name}: `workspace` без сети `default` — он не сможет скачать файлы "
                "пользователя из внешнего хранилища, и рабочий каталог будет пуст"
            )
    return problems


def check_sandbox_stays_offline() -> list[str]:
    """Сама песочница обязана оставаться без сети, что бы ни решили про сайдкар."""
    policy = next((path for path in POLICY_CANDIDATES if path.exists()), None)
    if policy is None:
        return ["workspace policy: файла нет"]
    text = policy.read_text(encoding="utf-8")
    if not re.search(r'^\s*network:\s*str\s*=\s*"none"', text, re.M):
        return [
            "workspace/service/policy.py: у песочницы дефолт `network` больше не `none` — "
            "код пользователя получил сеть, а этого решения никто не принимал"
        ]
    return []


def main() -> None:
    problems = check_compose() + check_sandbox_stays_offline()
    if problems:
        print("Изоляция сайдкара песочницы нарушена:", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        raise SystemExit(1)
    print("workspace: наружу да, внутрь нет; песочницы без сети — OK")


if __name__ == "__main__":
    main()
