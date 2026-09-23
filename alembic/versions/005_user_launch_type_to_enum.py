"""Convert profile.user_launch.type column to PostgreSQL ENUM service_type

Revision ID: 005_user_launch_type_to_enum
Revises: 004_add_calendar_service_type_check
Create Date: 2025-12-26 00:00:00.000000

Переводит свободный строковый столбец `profile.user_launch.type` в нативный
PostgreSQL ENUM `service_type`, чтобы значения проверялись на уровне БД.

Идемпотентно и text-safe: если столбец уже enum — выходит; неизвестные/NULL
значения приводятся к единственному валидному `CHAT` (TRAIN/DEFAULT/CALENDAR
больше не используются), без аварийного raise. См. также миграцию 004.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "005_user_launch_type_to_enum"
down_revision = "004_add_calendar_service_type_check"
branch_labels = None
depends_on = None

ALLOWED = ("TRAIN", "DEFAULT", "CALENDAR")
ENUM_NAME = "service_type"


def upgrade() -> None:
    conn = op.get_bind()

    # Таблицы может ещё не быть на этом шаге цепочки — конвертировать нечего.
    insp = sa.inspect(conn)
    if not insp.has_table("user_launch", schema="profile"):
        return

    # Идемпотентность: если колонка уже enum service_type — выходим.
    udt = conn.execute(
        sa.text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema = 'profile' AND table_name = 'user_launch' "
            "AND column_name = 'type'"
        )
    ).scalar()
    if udt == ENUM_NAME:
        return

    # Колонка ещё текстовая. TRAIN/DEFAULT/CALENDAR больше не используются —
    # единственное валидное значение CHAT. Неизвестные/NULL приводим к CHAT
    # (text-сравнение, без коэрсинга несуществующих enum-литералов) вместо
    # аварийного raise, который ронял весь upgrade.
    conn.execute(
        sa.text(
            "UPDATE profile.user_launch SET type = 'CHAT' "
            "WHERE type IS NULL OR type::text <> 'CHAT'"
        )
    )

    # Снимаем устаревший CHECK, если остался от прежних версий.
    try:
        op.drop_constraint(
            "ck_profile_user_launch_type_allowed", "user_launch", schema="profile", type_="check"
        )
    except Exception:
        pass

    enum = postgresql.ENUM("CHAT", name=ENUM_NAME)
    enum.create(conn, checkfirst=True)
    op.execute(
        f"ALTER TABLE profile.user_launch "
        f"ALTER COLUMN type TYPE {ENUM_NAME} USING type::text::{ENUM_NAME}"
    )


def downgrade() -> None:
    # Revert column back to plain varchar
    op.execute("ALTER TABLE profile.user_launch ALTER COLUMN type TYPE varchar(50)")
    # Drop enum type
    op.execute(f"DROP TYPE IF EXISTS {ENUM_NAME}")
