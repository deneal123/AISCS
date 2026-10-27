"""Expiry cannot erase retained obligations or overwrite a terminal settlement.

Revision ID: 048_retained_expiry
Revises: 047_command_receipts
"""

from alembic import op

revision = "048_retained_expiry"
down_revision = "047_command_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION profile.expire_reservation_if_past()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status = 'reserved' AND NEW.harness_task_id IS NULL
               AND NEW.expires_at IS NOT NULL AND NEW.expires_at < now() THEN
                NEW.status := 'expired';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM profile.token_reservations
                       WHERE status='reserved' AND harness_task_id IS NOT NULL) THEN
                RAISE EXCEPTION 'Outstanding harness reservations require reconciliation';
            END IF;
        END $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION profile.expire_reservation_if_past()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.expires_at IS NOT NULL AND NEW.expires_at < now() THEN
                NEW.status := 'expired';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
