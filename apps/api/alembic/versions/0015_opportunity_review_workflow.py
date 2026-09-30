"""opportunity review workflow

Revision ID: 0015_opportunity_review_workflow
Revises: 0014_preferred_marketplace_categories
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_opportunity_review_workflow"
down_revision = "0014_preferred_marketplace_categories"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("curator_candidates") as batch:
        batch.add_column(sa.Column("opportunity_review_status", sa.String(length=24), nullable=False, server_default="PENDING"))
        batch.add_column(sa.Column("opportunity_reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("opportunity_review_reason", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("curator_candidates") as batch:
        batch.drop_column("opportunity_review_reason")
        batch.drop_column("opportunity_reviewed_at")
        batch.drop_column("opportunity_review_status")
