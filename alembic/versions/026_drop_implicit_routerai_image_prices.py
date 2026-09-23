"""Remove stale provider-less image prices superseded by RouterAI catalog sync.

Revision ID: 026_drop_implicit_routerai_image_prices
Revises: 025_gigachat_current_tariffs
"""

from alembic import op


revision = "026_drop_implicit_routerai_image_prices"
down_revision = "025_gigachat_current_tariffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These five records came from an older RouterAI catalog, but had no provider
    # field before revision 024. Current provider-specific records are installed
    # by sync_provider_pricing.py, so retaining them as a global fallback would
    # again apply RouterAI rates to another provider.
    op.execute(
        "DELETE FROM profile.model_pricing "
        "WHERE provider = '' AND updated_by = 'замер каталога routerai'"
    )


def downgrade() -> None:
    pass
