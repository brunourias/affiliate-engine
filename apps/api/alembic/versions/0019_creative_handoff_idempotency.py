"""controlled Creative handoff provenance and idempotency

Revision ID: 0019_creative_handoff_idempotency
Revises: 0018_campaign_assessment_idempotency
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_creative_handoff_idempotency"
down_revision = "0018_campaign_assessment_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable values preserve all historical creatives. UNIQUE still permits
    # multiple NULL keys, while preventing duplicate controlled handoffs.
    with op.batch_alter_table("creatives") as batch:
        batch.add_column(sa.Column("creation_source", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("creation_key", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("source_campaign_approval_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("source_assessment_id", sa.String(length=36), nullable=True))
        batch.create_unique_constraint("uq_creatives_creation_key", ["creation_key"])
        batch.create_foreign_key("fk_creatives_source_campaign_approval", "approvals", ["source_campaign_approval_id"], ["id"])
        batch.create_foreign_key("fk_creatives_source_assessment", "curator_assessments", ["source_assessment_id"], ["id"])


def downgrade():
    with op.batch_alter_table("creatives") as batch:
        batch.drop_constraint("fk_creatives_source_assessment", type_="foreignkey")
        batch.drop_constraint("fk_creatives_source_campaign_approval", type_="foreignkey")
        batch.drop_constraint("uq_creatives_creation_key", type_="unique")
        batch.drop_column("source_assessment_id")
        batch.drop_column("source_campaign_approval_id")
        batch.drop_column("creation_key")
        batch.drop_column("creation_source")
