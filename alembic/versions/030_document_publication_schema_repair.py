"""Repair early Document Forge publication tables.

Revision ID: 030_document_pub_repair
Revises: 029_document_publication_jobs

The S34 table was exercised on development installations while its contract was
still being completed.  Some databases therefore recorded revision 029 before
the optional assistant-message link was present in that revision.  Keep this
repair idempotent so both those databases and fresh installations converge on
the same schema.
"""

from __future__ import annotations

from alembic import op

revision = "030_document_pub_repair"
down_revision = "029_document_publication_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE profile.document_publication_job
        ADD COLUMN IF NOT EXISTS assistant_message_id BIGINT NULL
        """
    )


def downgrade() -> None:
    # Revision 029 owns the column for fresh databases.  Removing it here would
    # make a downgrade depend on whether this repair actually created it.
    pass
