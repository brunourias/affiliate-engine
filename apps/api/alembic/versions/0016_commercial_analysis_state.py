"""commercial analysis state

Revision ID: 0016_commercial_analysis_state
Revises: 0015_opportunity_review_workflow
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_commercial_analysis_state"
down_revision = "0015_opportunity_review_workflow"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("curator_candidates") as batch:
        batch.add_column(sa.Column("commercial_analysis_status", sa.String(length=32), nullable=False, server_default="NOT_STARTED"))
        batch.add_column(sa.Column("commercial_analysis_last_run_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("commercial_analysis_blocker", sa.String(length=64), nullable=True))

def downgrade():
    with op.batch_alter_table("curator_candidates") as batch:
        batch.drop_column("commercial_analysis_blocker")
        batch.drop_column("commercial_analysis_last_run_at")
        batch.drop_column("commercial_analysis_status")
