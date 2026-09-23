"""Создать/сбросить DEV-пользователя с ПОДТВЕРЖДЁННЫМ email и заданным паролем.

Зачем: штатная регистрация двухшаговая (email + OTP-код по SMTP), что неудобно для
локальной разработки и E2E-прогонов. Этот скрипт создаёт подтверждённый аккаунт
напрямую в БД — с argon2-хешем пароля (как у приложения) и email_verified=true.
Штатный session/OTP-контракт приложения он не обходит. Идемпотентно: повтор для
того же email сбрасывает пароль и переподтверждает.

Запускается через `make create-user EMAIL=... PASSWORD=...` (пайпится в python
контейнера). Прямой вызов:
    docker exec -i gpthub-dev-backend-1 python - <email> <password> < scripts/create_dev_user.py
"""

from __future__ import annotations

import asyncio
import sys


def _valid_password(pwd: str) -> bool:
    # Та же политика, что в auth_service.register_user: 8+ символов, буква и цифра.
    return len(pwd) >= 8 and any(c.isalpha() for c in pwd) and any(c.isdigit() for c in pwd)


async def _run(email: str, password: str) -> None:
    from argon2 import PasswordHasher

    from service.infrastructure.database.postgresql import PgConnector
    from service.services.profile.persistence.profile_repository import ProfileRepository
    from service.settings import Config

    email = email.strip().lower()
    if "@" not in email:
        print(f"ОШИБКА: '{email}' не похоже на email.")
        raise SystemExit(2)
    if not _valid_password(password):
        print("ОШИБКА: пароль должен быть 8+ символов и содержать букву и цифру.")
        raise SystemExit(2)

    config = Config()
    repo = ProfileRepository(PgConnector(config.pg))
    ph = PasswordHasher()

    existing = await repo.fetch_user_by_email(email)
    if existing:
        await repo.update_password_hash(str(existing.id), ph.hash(password))
        await repo.set_email_verified(str(existing.id))
        user_id = existing.id
        action = "обновлён (пароль сброшен, email переподтверждён)"
    else:
        # consent_version="dev" → проставляются метки согласий (create_user), чтобы
        # аккаунт не считался «без согласий»; available_launches=10 ставит сам репозиторий.
        created = await repo.create_user(
            email=email, password_hash=ph.hash(password), consent_version="dev"
        )
        await repo.set_email_verified(str(created.id))
        user_id = created.id
        action = "создан и подтверждён"

    print(f"OK: пользователь {email} {action}. id={user_id}")
    # Never echo credentials: this helper is commonly invoked from CI/E2E
    # wrappers whose stdout is retained as an artifact.
    print("Учётные данные обновлены; пароль в вывод не печатается.")
    # Личный граф пользователя в graphify-сайдкаре (namespace user_graph_id).
    print(f"graph_id в graphify: user-{user_id}")


def main() -> None:
    # sys.argv при запуске `python - <email> <password>`: ['-', email, password].
    args = [a for a in sys.argv[1:] if a]
    if len(args) < 2:
        print("Usage: python scripts/create_dev_user.py <email> <password>")
        raise SystemExit(2)
    asyncio.run(_run(args[0], args[1]))


if __name__ == "__main__":
    main()
