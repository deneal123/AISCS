"""Исходное имя файла рядом с ключом хранилища.

🔴 ЗАЧЕМ. `file_name` — это КЛЮЧ ХРАНИЛИЩА (`uploads/CHAT/123f5c3b….json`), а имя, под
которым файл прислал человек, не сохранялось нигде. Пока файлы жили только в объектном
хранилище, это было незаметно: наружу их отдавали презайнед-ссылкой. С приходом рабочего
каталога они стали ВИДИМЫ — и в дереве песочницы, и у агента в `ws_list` появились
шестнадцатеричные имена, по которым не понять, что это за файл. Живой прогон:
`uploads/CHAT/123f5c3b1a2a4c8cb6977fa42ec375d1.json` вместо `рассылка.json`.

⚠️ Колонка NULLABLE и без обратного заполнения: у старых записей исходного имени просто
нет, и выдумывать его нельзя. Потребитель падает на basename ключа — как было.

Revision ID: 022_user_file_original_name
Revises: 021_merge_active_quotas
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "022_user_file_original_name"
down_revision = "021_merge_active_quotas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_file",
        sa.Column("original_name", sa.String(length=1000), nullable=True),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_column("user_file", "original_name", schema="profile")
