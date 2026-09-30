"""campaign handoff creation idempotency

Revision ID: 0018_campaign_assessment_idempotency
Revises: 0017_campaign_handoff_gate
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_campaign_assessment_idempotency"
down_revision = "0017_campaign_handoff_gate"
branch_labels = None
depends_on = None

def upgrade():
    # Nullable key intentionally preserves legitimate historical duplicates.
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(sa.Column("creation_source", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("creation_key", sa.String(length=100), nullable=True))
        batch.create_unique_constraint("uq_campaigns_creation_key", ["creation_key"])

def downgrade():
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_constraint("uq_campaigns_creation_key", type_="unique")
        batch.drop_column("creation_key")
        batch.drop_column("creation_source")
