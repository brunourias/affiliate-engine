"""candidate triage fields

Revision ID: 0013_candidate_triage
Revises: 0012_marketplace_oauth_credentials
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_candidate_triage"
down_revision = "0012_marketplace_oauth_credentials"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("curator_candidates") as batch:
        batch.add_column(sa.Column("triage_score", sa.Integer()))
        batch.add_column(sa.Column("triage_status", sa.String(20)))
        batch.add_column(sa.Column("triage_reasons", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("triage_marked_for_enrichment", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("triage_evaluated_at", sa.DateTime(timezone=True)))


def downgrade():
    with op.batch_alter_table("curator_candidates") as batch:
        batch.drop_column("triage_evaluated_at")
        batch.drop_column("triage_marked_for_enrichment")
        batch.drop_column("triage_reasons")
        batch.drop_column("triage_status")
        batch.drop_column("triage_score")
