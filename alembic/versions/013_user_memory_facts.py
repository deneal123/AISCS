"""Long-term memory: own structured facts table (bypass MemOS extraction).

Провайдер памяти (MemOS) на /product/add переписывает наши факты своей
англоязычной LLM-экстракцией (summary-блобы, служебные префиксы вроде «37»,
почти константный score «99%»). Чтобы память была структурированной, русской,
валидной и с осмысленной уверенностью, храним факты в СВОЁМ реестре и полностью
контролируем запись/чтение. MemOS остаётся опциональным (не источник истины).

Revision ID: 013_user_memory_facts
Revises: 012_admin_panel
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "013_user_memory_facts"
down_revision = "012_admin_panel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS profile;")

    # Собственный реестр долговременных фактов о пользователе. Пишется нашей
    # guardrails-экстракцией (только устойчивые русскоязычные факты). Дедуп на
    # запись — по (user_id, content_hash) нормализованного текста факта.
    op.create_table(
        "user_memory_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("fact_type", sa.String(32), nullable=False, server_default="general"),
        sa.Column("fact_key", sa.String(255), nullable=False),
        sa.Column("fact_value", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        # Осмысленная уверенность 0..1 (может быть NULL — тогда UI её не показывает,
        # никакого фейкового «99%»).
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("source_thread_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "content_hash", name="uq_user_memory_facts_user_content"
        ),
        schema="profile",
    )
    op.create_index(
        "ix_user_memory_facts_user",
        "user_memory_facts",
        ["user_id"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_memory_facts_user", table_name="user_memory_facts", schema="profile"
    )
    op.drop_table("user_memory_facts", schema="profile")
