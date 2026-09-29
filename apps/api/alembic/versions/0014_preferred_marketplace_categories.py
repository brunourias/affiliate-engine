"""preferred marketplace categories

Revision ID: 0014_preferred_marketplace_categories
Revises: 0013_candidate_triage
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_preferred_marketplace_categories"
down_revision = "0013_candidate_triage"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(sa.Column("preferred_marketplace_category_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("include_global_trends_outside_preferred_categories", sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("include_global_trends_outside_preferred_categories")
        batch.drop_column("preferred_marketplace_category_ids")
