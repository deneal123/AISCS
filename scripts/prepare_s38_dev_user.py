"""Explicit dev-only account provisioning; run inside the dev backend container.

Generated credentials are written mode 0600 to /tmp/.env.s38, never stdout.
Copy that generated file to an ignored local .env.s38 for authenticated smoke tests.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
import secrets

from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.cache.cache import RedisCacheService
from service.infrastructure.cache.manager import RedisManager
from service.services.admin.persistence.admin_repository import AdminRepository
from service.services.billing.application.billing_service import BillingService
from service.services.billing.persistence.billing_repository import BillingRepository
from service.services.profile.application.auth_service import AuthService
from service.services.profile.application.profile_service import ProfileService
from service.services.profile.persistence.auth_repository import AuthRepository
from service.services.profile.persistence.profile_repository import ProfileRepository
from service.settings import config


async def main():
    if os.environ.get("S38_DEV_PROVISION") != "1":
        raise SystemExit("explicit_dev_provision_required")
    logging.disable(logging.CRITICAL)
    connector = PgConnector(config.pg)
    repo = ProfileRepository(connector)
    cache = RedisCacheService(RedisManager(config.redis).get_client(), config.redis)
    profile = ProfileService(config.profile, repo, cache=cache)
    # EmailStr rejects .test even on read; example.com is reserved and syntactically valid.
    email = "s38-video-acceptance@example.com"
    credentials = Path("/tmp/.env.s38")
    user = await repo.fetch_user_by_email(email)
    if user is None:
        legacy = await repo.fetch_user_by_email("s38-video-acceptance@dev.gpthub.test")
        if legacy is not None:
            legacy.email = email
            user = await repo.update_user_profile(legacy)
    created = user is None
    password = None
    if user is None:
        password = secrets.token_urlsafe(32)
        user = await profile.create_new_user(email, password)
        await repo.set_email_verified(str(user.id))
    elif credentials.exists():
        password = json.loads(credentials.read_text())["password"]
    else:
        # After container recreation, copy the ignored operator artifact back
        # before renewing the session; never overwrite it with a null password.
        raise SystemExit("existing_dev_credentials_required")
    billing = BillingService(BillingRepository(connector), config.billing)
    before = await billing.get_balance(str(user.id))
    refresh_only = os.environ.get("S38_REFRESH_SESSION_ONLY") == "1"
    # Provision once. Refreshing an existing test user must not reimburse live
    # usage or conceal billing discrepancies by topping the balance up again.
    delta = 1_000_000 - before.total if created and not refresh_only else 0
    if delta:
        await AdminRepository(connector).adjust_topup_credits(
            user_id=str(user.id),
            delta=delta,
            reason="S38 isolated dev acceptance balance",
            updated_by="s38-dev-operator",
        )
    after = await billing.get_balance(str(user.id))
    if created and not refresh_only and after.total != 1_000_000:
        raise SystemExit("dev_balance_mismatch")
    auth = AuthService(config.auth, AuthRepository(connector), profile, config.email)
    await profile._invalidate_profile_cache(
        user.id, "s38-video-acceptance@dev.gpthub.test"
    )
    await profile._invalidate_profile_cache(user.id, email)
    session = await auth._create_activated_session(user, "S38 dev acceptance", None)
    fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(
            {"email": email, "password": password, "token": session.token}, output
        )
    print(
        json.dumps(
            {
                "created": created,
                "balance_before": before.total,
                "adjustment": delta,
                "balance_after": after.total,
            }
        )
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        # Do not expose connection strings, SDK bodies or credentials from an
        # operator provisioning failure.
        raise SystemExit("dev_provision_failed") from None
