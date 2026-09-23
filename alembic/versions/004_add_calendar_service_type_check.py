"""Add check constraint to user_launch.type to include CALENDAR

Revision ID: 004_add_calendar_service_type_check
Revises: 003_drop_phone_column
Create Date: 2025-12-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_add_calendar_service_type_check"
# Fix: previous migration file uses revision '017_drop_phone' (003 file's revision).
# Align down_revision so Alembic can build the correct revision map.
down_revision: str | Sequence[str] | None = "017_drop_phone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "ck_profile_user_launch_type_allowed"
ALLOWED = ("TRAIN", "CALENDAR")


def upgrade() -> None:
    # Историческая проверка для значений TRAIN/CALENDAR, которых в системе больше
    # нет. service_type теперь PostgreSQL enum ({CHAT}) и сам гарантирует
    # валидность значений колонки, поэтому отдельный CHECK не нужен.
    #
    # No-op: раньше здесь сравнивался enum-столбец с литералом 'TRAIN', что на
    # современной схеме падало с asyncpg InvalidTextRepresentationError
    # (invalid input value for enum service_type: "TRAIN") и откатывало весь
    # `alembic upgrade`, не давая бэкенду стартовать.
    return


def downgrade() -> None:
    try:
        op.drop_constraint(CONSTRAINT_NAME, "user_launch", schema="profile", type_="check")
    except Exception:
        # best-effort cleanup
        conn = op.get_bind()
        conn.execute(sa.text(f"/* Unable to drop {CONSTRAINT_NAME} - may not exist */"))
