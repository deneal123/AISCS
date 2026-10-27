"""Новый синтетический владелец и thread без неявного выбора среды IDE/PDF."""

from uuid import uuid4

from sqlalchemy import text


async def actor_thread(container, *, initial_credits=100000, topup_credits=0):
    from service.models.db.db_models import User
    from service.services.chat.persistence.chat_repository import ChatRepository

    assert type(initial_credits) is int and 0 < initial_credits <= 1_000_000_000
    assert type(topup_credits) is int and 0 <= topup_credits <= 1_000_000_000
    connector = container.infra.pg_connector
    actor, thread = uuid4(), uuid4()
    async with connector.get_session_context() as db:
        db.add(
            User(
                id=actor,
                email=f"harness-{actor}@example.test",
                password_hash="!disabled",
                available_launches=initial_credits,
                email_verified=True,
            )
        )
        if topup_credits:
            await db.flush()
            await db.execute(
                text('UPDATE profile."user" SET topup_credit_balance=:credits WHERE id=:actor'),
                {"credits": topup_credits, "actor": actor},
            )
        await db.commit()
    await ChatRepository(connector).create_thread(actor, "Harness acceptance", str(thread))
    return actor, thread
