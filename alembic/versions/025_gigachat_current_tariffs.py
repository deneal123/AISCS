"""Refresh all active GigaChat text model tariffs.

The official synchronous pay-as-you-go tariff effective from 2026-02-01 is
0.065/0.5/0.65 RUB per 1K tokens for Lite/Pro/Max respectively. Both the
original and GigaChat-2 IDs point to those tiers.

Revision ID: 025_gigachat_current_tariffs
Revises: 024_provider_model_pricing
"""

from alembic import op


revision = "025_gigachat_current_tariffs"
down_revision = "024_provider_model_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preview/archived names have no current published tariff. Do not leave a
    # stale explicit price that would silently beat the fallback chain.
    op.execute("DELETE FROM profile.model_pricing WHERE provider = 'gigachat'")
    op.execute(
        """
        INSERT INTO profile.model_pricing
            (provider, model_id, price_in_rub_per_1k, price_out_rub_per_1k,
             model_class, updated_by, updated_at)
        VALUES
            ('gigachat', 'GigaChat',       0.0650000000, 0.0650000000, 'fast',  'system:gigachat-tariff-2026-02-01', now()),
            ('gigachat', 'GigaChat-2',     0.0650000000, 0.0650000000, 'fast',  'system:gigachat-tariff-2026-02-01', now()),
            ('gigachat', 'GigaChat-Pro',   0.5000000000, 0.5000000000, 'large', 'system:gigachat-tariff-2026-02-01', now()),
            ('gigachat', 'GigaChat-2-Pro', 0.5000000000, 0.5000000000, 'large', 'system:gigachat-tariff-2026-02-01', now()),
            ('gigachat', 'GigaChat-Max',   0.6500000000, 0.6500000000, 'large', 'system:gigachat-tariff-2026-02-01', now()),
            ('gigachat', 'GigaChat-2-Max', 0.6500000000, 0.6500000000, 'large', 'system:gigachat-tariff-2026-02-01', now())
        ON CONFLICT (provider, model_id) DO UPDATE SET
            price_in_rub_per_1k = EXCLUDED.price_in_rub_per_1k,
            price_out_rub_per_1k = EXCLUDED.price_out_rub_per_1k,
            model_class = EXCLUDED.model_class,
            updated_by = EXCLUDED.updated_by,
            updated_at = now();
        """
    )


def downgrade() -> None:
    # The former GigaChat values were not an authoritative tariff either.
    pass
