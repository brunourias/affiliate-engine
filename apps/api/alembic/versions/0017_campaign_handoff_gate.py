"""campaign handoff gate

Revision ID: 0017_campaign_handoff_gate
Revises: 0016_commercial_analysis_state
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_campaign_handoff_gate"
down_revision = "0016_commercial_analysis_state"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("curator_candidates") as batch:
        batch.add_column(sa.Column("campaign_handoff_status", sa.String(length=24), nullable=False, server_default="NOT_DECIDED"))
        batch.add_column(sa.Column("campaign_handoff_assessment_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("campaign_handoff_reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("campaign_handoff_reason", sa.Text(), nullable=True))
        batch.create_foreign_key("fk_curator_candidates_campaign_handoff_assessment", "curator_assessments", ["campaign_handoff_assessment_id"], ["id"])

def downgrade():
    with op.batch_alter_table("curator_candidates") as batch:
        batch.drop_constraint("fk_curator_candidates_campaign_handoff_assessment", type_="foreignkey")
        batch.drop_column("campaign_handoff_reason")
        batch.drop_column("campaign_handoff_reviewed_at")
        batch.drop_column("campaign_handoff_assessment_id")
        batch.drop_column("campaign_handoff_status")
