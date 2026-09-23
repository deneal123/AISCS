"""Split the model-price registry by actual provider.

The same model id can be served by RouterAI and OpenRouter at different prices.
Usage already contains the provider selected after failover, so pricing must use
the pair rather than a global model-id key.

Revision ID: 024_provider_model_pricing
Revises: 023_gigachat_tariff_2026_02
"""

from alembic import op


revision = "024_provider_model_pricing"
down_revision = "023_gigachat_tariff_2026_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ten decimal places retain the sub-kopeck per-1K rates returned by provider
    # catalogs; the old Numeric(12, 6) rounded inexpensive models materially.
    op.execute(
        "ALTER TABLE profile.model_pricing "
        "ALTER COLUMN price_in_rub_per_1k TYPE numeric(18, 10), "
        "ALTER COLUMN price_out_rub_per_1k TYPE numeric(18, 10)"
    )
    op.execute(
        "ALTER TABLE profile.model_pricing "
        "ADD COLUMN provider varchar(64) NOT NULL DEFAULT ''"
    )
    # Preserve the provenance of existing records while placing known provider
    # catalogs into their own namespace. Empty provider remains an explicit
    # backwards-compatible shared manual tariff.
    op.execute(
        "UPDATE profile.model_pricing SET provider = 'routerai' "
        "WHERE updated_by = 'routerai-seed'"
    )
    op.execute(
        "UPDATE profile.model_pricing SET provider = 'gigachat' "
        "WHERE model_id ILIKE 'GigaChat%'"
    )
    op.execute("ALTER TABLE profile.model_pricing DROP CONSTRAINT model_pricing_pkey")
    op.execute(
        "ALTER TABLE profile.model_pricing "
        "ADD CONSTRAINT model_pricing_pkey PRIMARY KEY (provider, model_id)"
    )


def downgrade() -> None:
    # A downgrade cannot preserve two provider-specific rates for one model id;
    # retain the newest row deterministically before restoring the old key.
    op.execute(
        "DELETE FROM profile.model_pricing older "
        "USING profile.model_pricing newer "
        "WHERE older.model_id = newer.model_id "
        "AND older.provider <> newer.provider "
        "AND older.updated_at < newer.updated_at"
    )
    op.execute("ALTER TABLE profile.model_pricing DROP CONSTRAINT model_pricing_pkey")
    op.execute("ALTER TABLE profile.model_pricing ADD CONSTRAINT model_pricing_pkey PRIMARY KEY (model_id)")
    op.execute("ALTER TABLE profile.model_pricing DROP COLUMN provider")
    op.execute(
        "ALTER TABLE profile.model_pricing "
        "ALTER COLUMN price_in_rub_per_1k TYPE numeric(12, 6), "
        "ALTER COLUMN price_out_rub_per_1k TYPE numeric(12, 6)"
    )
